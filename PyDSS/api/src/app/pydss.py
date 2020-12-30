import os
import logging
from multiprocessing import current_process
import inspect
from queue import Empty
from PyDSS.dssInstance import OpenDSS
from PyDSS.valiate_settings import validate_settings
from PyDSS.api.src.web.parser import restructure_dictionary
#from PyDSS.api.src.app.arrow_writer import ArrowWriter
from PyDSS.api.src.app.JSON_writer import JSONwriter
from naerm_core.web.client_requests import send_sync_request
from naerm_core.notification.notifier import Notifier
import json
from http import HTTPStatus
from zipfile import ZipFile
import re
import shutil

logger = logging.getLogger(__name__)

class PyDSS:

    commands = {
        "run": None
    }

    def __init__(self, helics_, services, event=None, queue=None, parameters=None):

        self.initalized = False
        self.uuid = current_process().name

        ''' TODO: work on logging.yaml file'''
        
        logging.info("{} - initialized ".format({self.uuid}))

        self.shutdownevent = event
        self.queue = queue
        self.data_service_url = services['bes_data']
        notifications_uri = services['notifications_data']
        self.notifier = Notifier(notifications_uri)
        

        try:
            parameters['Broker'] = helics_['broker']['host']
            parameters['Broker port'] = helics_['broker']['port']
            parameters['Co-simulation Mode'] = False
            
            """ If the project path is uuid, grab content from AWS S3"""
            if not os.path.exists(parameters["Project Path"]):
                parameters = self.update_project_params(parameters)
                if parameters is None:
                    self.queue({
                        "Status": 500,
                        "Message": "Error creating project",
                        "UUID": self.uuid
                    })
                    return
            params = restructure_dictionary(parameters)
            self.parameters = parameters
            self.pydss_obj = OpenDSS(params)
            export_path = os.path.join(self.pydss_obj._dssPath['Export'], params['Project']['Active Scenario'])
            Steps, sTime, eTime = self.pydss_obj._dssSolver.SimulationSteps()
            self.a_writer = JSONwriter(export_path, self.data_service_url, Steps, self.notify)
            self.initalized = True
        except Exception as e:
            print(e)
            result = {"Status": 500, "Message": f"Failed to create a PyDSS instance"}
            self.queue.put(result)
            return

        #self.RunSimulation()
        logger.info("{} - pydss dispatched".format(self.uuid))

        result = {
            "Status": 200,
            "Message": "PyDSS {} successfully initialized.".format(self.uuid),
            "UUID": self.uuid
        }

        if self.queue != None: self.queue.put(result)

        self.run_process()

    def notify(self, msg: str, timestep: float=None, log_level:
                                                    int=logging.INFO):
        """ Send notification to the notification client. """
        self.notifier.notify(self.cosim_uuid, self.federate_service, msg, 
                             timestep, log_level)

    def update_project_params(self,params):

        """ Grab file and metadata info of case file """
        self.tmp_folder = os.path.join(os.path.dirname(__name__), '..', 'tmp')
        file_uuid = params['Project Path']

        """ If folder does not exist, create a temporary folder"""
        if not os.path.exists(self.tmp_folder):
            os.mkdir(self.tmp_folder)

        folder_name = f"{params['Co-simulation UUID']}_{params['Federate name']}"
        self.folder_name = folder_name
        case_file_url = f'{self.data_service_url}/case_files/uuid/{file_uuid}'

        """ Creating a project folder and removing if already exists"""
        self.project_folder = os.path.join(self.tmp_folder, folder_name)
        if not os.path.exists(self.project_folder):
            os.mkdir(self.project_folder)
        else:
            shutil.rmtree(self.project_folder)
            os.mkdir(self.project_folder)
        
        """ Retrieve the file url from the BES Data API """
        file_response = send_sync_request(case_file_url, 'GET', body=None)
        file_data = json.loads(file_response.data.decode('utf-8'))

        if file_response.status == HTTPStatus.OK:
            file_url = file_data['file_url']
            file_format = file_data['format']

            """ Retrieve the file from AWS and store in the tmp directory """
            data_response = send_sync_request(file_url, 'GET')
            if data_response.status == HTTPStatus.OK:
                file = os.path.join(self.project_folder, f'{file_uuid}.{file_format}')
                with open(file, 'wb') as f:
                    f.write(data_response.data)

                """ Unzip the files """
                zip_path = os.path.join(self.project_folder, f'{file_uuid}.{file_format}')
                if zip_path.endswith('.zip'):
                    with ZipFile(zip_path, 'r') as zipObj:
                        zipObj.extractall(path=self.project_folder)
                    
                    os.remove(zip_path)
                
                    params.update({
                        'Project Path' : self.project_folder,
                        'Active Project' : file_data['case']['active_project'],
                        'Active Scenario' : file_data['case']['active_scenario'],
                        'DSS File' : file_data['case']['dss_file']
                    })
                    print(params)
                    #TODO: validate pydss project skeleton
                    
                    """ create log folder if not present """
                    log_folder  = os.path.join(self.project_folder, file_data['case']['active_project'], 'Logs')
                    if not os.path.exists(log_folder):
                        os.mkdir(log_folder)

                    return params
                else:
                    logger.error(f'PyDSS case file is not a zip file')
                    return None
            else:
                logger.error(f'Error fetching data from AWS S3')
                return None

        else:
            logger.error(f'Error fetching PyDSS project!')
            return None
    
    def run_process(self):
        logger.info("PyDSS simulation starting")
        while not self.shutdownevent.is_set():
            try:
                task = self.queue.get()
                if task == 'END':
                    break
                elif "parameters" not in task:
                    result = {
                        "Status": 500,
                        "Message": "No parameters passed"
                    }
                else:
                    command = task["command"]
                    parameters = task["parameters"]
                    if hasattr(self, command):
                        func = getattr(self, command)
                        status, msg = func(parameters)
                        result = {"Status": status, "Message": msg, "UUID": self.uuid}
                    else:
                        logger.info(f"{command} is not a valid PyDSS command")
                        result = {"Status": 500, "Message": f"{command} is not a valid PyDSS command"}
                self.queue.put(result)
            
            except Empty:
                continue

            except (KeyboardInterrupt, SystemExit):
                break
        logger.info(f"PyDSS subprocess {self.uuid} has ended")


    def close_instance(self):
        del self.pydss_obj
        logger.info(f'PyDSS case {self.uuid} closed.')

    def restructure_results(self, results):
        restructured_results = {}
        for k, val in results.items():
            if "." not in k:
                class_name = "Bus"
                elem_name = k
            else:
                class_name, elem_name = k.split(".")
            if class_name not in restructured_results:
                restructured_results[class_name] = {}
            if not isinstance(val, complex):
                restructured_results[class_name][elem_name] = val

        return restructured_results


    def run(self, params):
        if self.initalized:
            try:
                Steps, sTime, eTime = self.pydss_obj._dssSolver.SimulationSteps()
                print("Steps:", Steps)

                for i in range(Steps):
                    results = self.pydss_obj.RunStep(i)
                    restructured_results = self.restructure_results(results)
                    
                    # Timestep data payload and metadata only in an inital timestep
                    self.a_writer.write(
                        self.parameters['Federate name'],
                        self.pydss_obj._dssSolver.GetTotalSeconds(),
                        restructured_results,
                        i,
                        fed_uuid=self.parameters['fed_uuid'],
                        cosim_uuid=self.parameters['Co-simulation UUID']
                    )

                # closing federate
                self.a_writer.send_timesteps()
                
                # Remove the project data
                if os.path.exists(os.path.join(self.tmp_folder, self.folder_name)):
                    shutil.rmtree(os.path.join(self.tmp_folder, self.folder_name))

                self.initalized = False
                return 200, f"Simulation complete..."
            except Exception as e:
                print(e)
                self.initalized = False
                return 500, f"Simulation crashed at at simulation time step: {self.pydss_obj._dssSolver.GetDateTime()}, {e}"
        else:
            return 500, f"No project initialized. Load a project first using the 'init' command"

    def registerPubSubs(self, params):
        subs = params["Subscriptions"]
        pubs = params["Publications"]
        self.pydss_obj._HI.registerPubSubTags(pubs, subs)
        return 200, f"Publications and subscriptions have been registered; Federate has entered execution mode"

if __name__ == '__main__':
    FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
    logger.basicConfig(level=logger.INFO, format=FORMAT)
    a = PyDSS()
    del a
