"""Contains functionality to configure PyDSS simulations."""

import logging
import os
import shutil
import tarfile
import zipfile

import h5py
import pandas as pd

import PyDSS
from PyDSS.common import PROJECT_TAR, PROJECT_ZIP, \
    SIMULATION_SETTINGS_FILENAME, DEFAULT_SIMULATION_SETTINGS_FILE, \
    ControllerType, ExportMode, MONTE_CARLO_SETTINGS_FILENAME,\
    filename_from_enum, VisualizationType, DEFAULT_MONTE_CARLO
from PyDSS.exceptions import InvalidParameter, InvalidConfiguration
from PyDSS.pyDSS import instance
from PyDSS.pydss_fs_interface import PyDssDirectoryInterface, \
    PyDssArchiveFileInterfaceBase, PyDssTarFileInterface, \
    PyDssZipFileInterface, PROJECT_DIRECTORIES, \
    SCENARIOS, STORE_FILENAME
from PyDSS.utils.utils import dump_data, load_data


logger = logging.getLogger(__name__)


DATA_FORMAT_VERSION = "1.0.0"


class PyDssProject:
    """Represents the project options for a PyDSS simulation."""
    def __init__(self, path, name, scenarios, simulation_config, fs_intf=None, simulation_file=None):
        self._name = name
        self._scenarios = scenarios
        self._simulation_file = simulation_file
        self._simulation_config = simulation_config
        self._project_dir = os.path.join(path, self._name)
        self._scenarios_dir = os.path.join(self._project_dir, SCENARIOS)
        self._fs_intf = fs_intf  # Only needed for reading a project that was
                                 # already executed.
        self._hdf_store = None

    @property
    def dss_files_path(self):
        """Return the path containing OpenDSS files.

        Returns
        -------
        str

        """
        return os.path.join(self._project_dir, "DSSfiles")

    def export_path(self, scenario):
        """Return the path containing export data.

        Parameters
        ----------
        scenario : str

        Returns
        -------
        str

        """
        return os.path.join(self._project_dir, "Exports", scenario)

    @property
    def hdf_store(self):
        """Return the HDFStore

        Returns
        -------
        pd.HDFStore

        """
        if self._hdf_store is None:
            raise InvalidConfiguration("hdf_store is not defined")
        return self._hdf_store

    @property
    def fs_interface(self):
        """Return the interface object used to read files.

        Returns
        -------
        PyDssFileSystemInterface

        """
        if self._fs_intf is None:
            raise InvalidConfiguration("fs interface is not defined")
        return self._fs_intf

    def get_hdf_store_filename(self):
        """Return the HDFStore filename.

        Returns
        -------
        str
            Path to the HDFStore.

        Raises
        ------
        InvalidConfiguration
            Raised if no store exists.

        """
        filename = os.path.join(self._project_dir, STORE_FILENAME)
        if not os.path.exists(filename):
            raise InvalidConfiguration(f"HDFStore does not exist")

        return filename

    def get_post_process_directory(self, scenario_name):
        """Return the post-process output directory for scenario_name.

        Parameters
        ----------
        scenario_name : str

        Returns
        -------
        str

        """
        # Make sure the scenario exists. This will throw if not.
        self.get_scenario(scenario_name)
        return os.path.join(
            self._project_dir, "Scenarios", scenario_name, "PostProcess"
        )

    def get_scenario(self, name):
        """Return the scenario with name.

        Parameters
        ----------
        name : str

        Returns
        -------
        PyDssScenario

        """
        for scenario in self._scenarios:
            if scenario.name == name:
                return scenario

        raise InvalidParameter(f"{name} is not a valid scenario")

    @property
    def name(self):
        """Return the project name.

        Returns
        -------
        str

        """
        return self._name

    @property
    def project_path(self):
        """Return the path to the project.

        Returns
        -------
        str

        """
        return self._project_dir

    @property
    def scenarios(self):
        """Return the project scenarios.

        Returns
        -------
        list
            list of PyDssScenario

        """
        return self._scenarios

    @property
    def simulation_config(self):
        """Return the simulation configuration

        Returns
        -------
        dict

        """
        return self._simulation_config

    def serialize(self):
        """Create the project on the filesystem."""
        os.makedirs(self._project_dir, exist_ok=True)
        for name in PROJECT_DIRECTORIES:
            os.makedirs(os.path.join(self._project_dir, name), exist_ok=True)
        self._serialize_scenarios()
        if self._simulation_file:
            dump_data(
                self._simulation_config,
                os.path.join(self._project_dir, self._simulation_file),
            )
        else:
            dump_data(
                self._simulation_config,
                os.path.join(self._project_dir, SIMULATION_SETTINGS_FILENAME),
            )

        logger.info("Initialized directories in %s", self._project_dir)

    @classmethod
    def create_project(cls, path, name, scenarios, simulation_config=None, options=None, simulation_file=None):
        """Create a new PyDssProject on the filesystem.

        Parameters
        ----------
        path : str
            path in which to create directories
        name : str
            project name
        scenarios : list
            list of PyDssScenario objects
        simulation_config : str
            simulation config file; if None, use default

        """
        if simulation_config is None:
            simulation_config = DEFAULT_SIMULATION_SETTINGS_FILE
        simulation_config = load_data(simulation_config)
        if options is not None:
            simulation_config.update(options)
        simulation_config["Project"]["Project Path"] = path
        simulation_config["Project"]["Active Project"] = name
        project = cls(path, name, scenarios, simulation_config, simulation_file)
        project._simulation_file = simulation_file
        project.serialize()
        sc_names = project.list_scenario_names()
        logger.info("Created project=%s with scenarios=%s at %s", name,
                    sc_names, path)
        return project

    def read_scenario_export_metadata(self, scenario_name):
        """Return the metadata for a scenario's exported data.

        Parameters
        ----------
        scenario_name : str

        Returns
        -------
        dict

        """
        if self._fs_intf is None:
            raise InvalidConfiguration("pydss fs interface is not defined")

        if scenario_name not in self.list_scenario_names():
            raise InvalidParameter(f"invalid scenario: {scenario_name}")

        return self._fs_intf.read_scenario_export_metadata(scenario_name)

    def list_scenario_names(self):
        return [x.name for x in self.scenarios]

    def run(self, logging_configured=True, tar_project=False, zip_project=False):
        """Run all scenarios in the project."""
        if isinstance(self._fs_intf, PyDssArchiveFileInterfaceBase):
            raise InvalidConfiguration("cannot run from an archived project")
        if tar_project and zip_project:
            raise InvalidParameter("tar_project and zip_project cannot both be True")
        if self._simulation_config['Project']['DSS File'] == "":
            raise InvalidConfiguration("a valid opendss file needs to be passed")


        inst = instance()
        self._simulation_config["Logging"]["Pre-configured logging"] = logging_configured
        store_filename = os.path.join(self._project_dir, STORE_FILENAME)
        driver = None
        if self._simulation_config["Exports"].get("Export Data In Memory", True):
            driver = "core"
        with h5py.File(store_filename, mode="w", driver=driver) as hdf_store:
            self._hdf_store = hdf_store
            self._hdf_store.attrs["version"] = DATA_FORMAT_VERSION
            for scenario in self._scenarios:
                self._simulation_config["Project"]["Active Scenario"] = scenario.name
                inst.run(self._simulation_config, self, scenario)

        if self._simulation_config["Exports"].get("Export Data Tables", False):
            # Hack. Have to import here. Need to re-organize to fix.
            from PyDSS.pydss_results import PyDssResults
            results = PyDssResults(self._project_dir)
            for scenario in results.scenarios:
                scenario.export_data()

        if tar_project:
            self._tar_project_files()
        elif zip_project:
            self._zip_project_files()

    def _serialize_scenarios(self):
        self._simulation_config["Project"]["Scenarios"] = []
        for scenario in self._scenarios:
            data = {
                "name": scenario.name,
                "post_process_infos": [],
            }
            for pp_info in scenario.post_process_infos:
                data["post_process_infos"].append(
                    {
                        "script": pp_info["script"],
                        "config_file": pp_info["config_file"],
                    }
                )
            self._simulation_config["Project"]["Scenarios"].append(data)
            scenario.serialize(
                os.path.join(self._scenarios_dir, scenario.name)
            )

    def _tar_project_files(self, delete=True):
        orig = os.getcwd()
        os.chdir(self._project_dir)
        try:
            filename = PROJECT_TAR
            to_delete = []
            with tarfile.open(filename, "w") as tar:
                for name in os.listdir("."):
                    if name in (PROJECT_TAR, STORE_FILENAME):
                        continue
                    tar.add(name)
                    if delete:
                        to_delete.append(name)

            for name in to_delete:
                if os.path.isfile(name):
                    os.remove(name)
                else:
                    shutil.rmtree(name)

            path = os.path.join(self._project_dir, filename)
            logger.info("Created project tar file: %s", path)
        finally:
            os.chdir(orig)

    def _zip_project_files(self, delete=True):
        orig = os.getcwd()
        os.chdir(self._project_dir)
        try:
            filename = PROJECT_ZIP
            to_delete = []
            with zipfile.ZipFile(filename, "w") as zipf:
                for root, dirs, files in os.walk("."):
                    if delete and root == ".":
                        to_delete += dirs
                    for filename in files:
                        if root == "." and filename in (PROJECT_ZIP, STORE_FILENAME):
                            continue
                        path = os.path.join(root, filename)
                        zipf.write(path)
                        # We delete files and directories at the root only.
                        if delete and root == ".":
                            to_delete.append(path)

            for name in to_delete:
                if os.path.isfile(name):
                    os.remove(name)
                else:
                    shutil.rmtree(name)

            path = os.path.join(self._project_dir, filename)
            logger.info("Created project zip file: %s", path)
        finally:
            os.chdir(orig)

    @staticmethod
    def load_simulation_config(project_path, scenario):
        """Return the simulation settings for a project, using defaults if the
        file is not defined.

        Parameters
        ----------
        project_path : str

        Returns
        -------
        dict

        """
        filename = os.path.join(project_path, scenario)
        if not os.path.exists(filename):
            filename = os.path.join(
                project_path,
                DEFAULT_SIMULATION_SETTINGS_FILE,
            )
            assert os.path.exists(filename)
        return load_data(filename)

    @classmethod
    def load_project(cls, path, options=None, in_memory=False, scenario=None):
        """Load a PyDssProject from directory.

        Parameters
        ----------
        path : str
            full path to existing project
        options : dict
            options that override the config file
        in_memory : bool
            If True, load all exported data into memory.

        """
        name = os.path.basename(path)

        if os.path.exists(os.path.join(path, PROJECT_TAR)):
            fs_intf = PyDssTarFileInterface(path)
        elif os.path.exists(os.path.join(path, PROJECT_ZIP)):
            fs_intf = PyDssZipFileInterface(path)
        else:
            fs_intf = PyDssDirectoryInterface(path, scenario)

        simulation_config = fs_intf.simulation_config
        if options is not None:
            for category, params in options.items():
                if category not in simulation_config:
                    simulation_config[category] = {}
                simulation_config[category].update(params)
            logger.info("Overrode config options: %s", options)

        scenarios = [
            PyDssScenario.deserialize(
                fs_intf,
                x["name"],
                post_process_infos=x["post_process_infos"],
            )
            for x in simulation_config["Project"]["Scenarios"]
        ]

        return PyDssProject(
            os.path.dirname(path),
            name,
            scenarios,
            simulation_config,
            fs_intf=fs_intf,
        )

    @classmethod
    def run_project(cls, path, options=None, tar_project=False, zip_project=False, scenario=None):
        """Load a PyDssProject from directory and run all scenarios.

        Parameters
        ----------
        path : str
            full path to existing project
        options : dict
            options that override the config file
        tar_project : bool
            tar project files after successful execution
        zip_project : bool
            zip project files after successful execution

        """
        project = cls.load_project(path, options=options, scenario=scenario)
        return project.run(tar_project=tar_project, zip_project=zip_project)


class PyDssScenario:
    """Represents a PyDSS Scenario."""

    DEFAULT_CONTROLLER_TYPES = (ControllerType.PV_CONTROLLER,)
    DEFAULT_VISUALIZATION_TYPES = (VisualizationType.FREQUENCY_PLOT, VisualizationType.HISTOGRAM_PLOT,
                                   VisualizationType.TABLE_PLOT, VisualizationType.THREEDIM_PLOT,
                                   VisualizationType.TIMESERIES_PLOT, VisualizationType.TOPOLOGY_PLOT,
                                   VisualizationType.VOLTDIST_PLOT, VisualizationType.XY_PLOT,)
    DEFAULT_EXPORT_MODE = ExportMode.BY_CLASS
    _SCENARIO_DIRECTORIES = (
        "ExportLists",
        "pyControllerList",
        "pyPlotList",
        "PostProcess",
        'Monte_Carlo'
    )
    REQUIRED_POST_PROCESS_FIELDS = ("script", "config_file")

    def __init__(self, name, controller_types=None, controllers=None,
                 export_modes=None, exports=None, visualizations=None,
                 post_process_infos=None, visualization_types=None):
        self.name = name
        self.post_process_infos = []

        if visualization_types is None and visualizations is None:
            self.visualizations = {
                x: self.load_visualization_config_from_type(x)
                for x in PyDssScenario.DEFAULT_VISUALIZATION_TYPES
            }
        elif visualization_types is not None:
            self.visualizations = {
                x: self.load_visualization_config_from_type(x)
                for x in visualization_types
            }
        elif isinstance(visualizations, str):
            basename = os.path.splitext(os.path.basename(visualizations))[0]
            visualization_type = VisualizationType(basename)
            self.visualizations = {visualization_type: load_data(controllers)}
        else:
            assert isinstance(visualizations, dict)
            self.visualizations = visualizations

        if (controller_types is None and controllers is None):
            self.controllers = {
                x: self.load_controller_config_from_type(x)
                for x in PyDssScenario.DEFAULT_CONTROLLER_TYPES
            }
        elif controller_types is not None:
            self.controllers = {
                x: self.load_controller_config_from_type(x)
                for x in controller_types
            }
        elif isinstance(controllers, str):
            basename = os.path.splitext(os.path.basename(controllers))[0]
            controller_type = ControllerType(basename)
            self.controllers = {controller_type: load_data(controllers)}
        else:
            assert isinstance(controllers, dict)
            self.controllers = controllers

        if export_modes is not None and exports is not None:
            raise InvalidParameter(
                "export_modes and exports cannot both be set"
            )
        if (export_modes is None and exports is None):
            mode = PyDssScenario.DEFAULT_EXPORT_MODE
            self.exports = {mode: self.load_export_config_from_mode(mode)}
        elif export_modes is not None:
            self.exports = {
                x: self.load_export_config_from_mode(x) for x in export_modes
            }
        elif isinstance(exports, str):
            mode = ExportMode(os.path.splitext(os.path.basename(exports))[0])
            self.exports = {mode: load_data(exports)}
        else:
            assert isinstance(exports, dict)
            self.exports = exports

        if post_process_infos is not None:
            for pp_info in post_process_infos:
                self.add_post_process(pp_info)

    @classmethod
    def deserialize(cls, fs_intf, name, post_process_infos):
        """Deserialize a PyDssScenario from a path.

        Parameters
        ----------
        fs_intf : PyDssFileSystemInterface
            object to read on-disk information
        name : str
            scenario name
        post_process_infos : list
            list of post_process_info dictionaries

        Returns
        -------
        PyDssScenario

        """
        controllers = fs_intf.read_controller_config(name)
        exports = fs_intf.read_export_config(name)
        visualizations = fs_intf.read_visualization_config(name)

        return cls(
            name,
            controllers=controllers,
            exports=exports,
            visualizations=visualizations,
            post_process_infos=post_process_infos,
        )

    def serialize(self, path):
        """Serialize a PyDssScenario to a directory.

        Parameters
        ----------
        path : str
            full path to scenario

        """
        os.makedirs(path, exist_ok=True)
        for name in self._SCENARIO_DIRECTORIES:
            os.makedirs(os.path.join(path, name), exist_ok=True)

        for controller_type, controllers in self.controllers.items():
            filename = os.path.join(
                path, "pyControllerList", filename_from_enum(controller_type)
            )
            dump_data(controllers, filename)

        for mode, exports in self.exports.items():
            dump_data(
                exports,
                os.path.join(path, "ExportLists", filename_from_enum(mode))
            )

        for visualization_type, visualizations in self.visualizations.items():
            filename = os.path.join(
                path, "pyPlotList", filename_from_enum(visualization_type)
            )
            dump_data(visualizations, filename)

        # @Danial the plots.toml file is not used by a single scenario.
        # It is used to craete plots that compare results from multiple scenarios
        dump_data(
            DEFAULT_MONTE_CARLO,
            os.path.join(path, "Monte_Carlo", MONTE_CARLO_SETTINGS_FILENAME)
        )

    @staticmethod
    def load_visualization_config_from_type(visualization_type):
        """Load a default visualization config from a type.

        Parameters
        ----------
        visualization_type : VisualizationType

        Returns
        -------
        dict

        """

        path = os.path.join(
            os.path.dirname(getattr(PyDSS, "__path__")[0]),
            "PyDSS",
            "defaults",
            "pyPlotList",
            filename_from_enum(visualization_type),
        )

        return load_data(path)

    @staticmethod
    def load_controller_config_from_type(controller_type):
        """Load a default controller config from a type.

        Parameters
        ----------
        controller_type : ControllerType

        Returns
        -------
        dict

        """

        path = os.path.join(
            os.path.dirname(getattr(PyDSS, "__path__")[0]),
            "PyDSS",
            "defaults",
            "pyControllerList",
            filename_from_enum(controller_type),
        )

        return load_data(path)

    @staticmethod
    def load_export_config_from_mode(export_mode):
        """Load a default export config from a type.

        Parameters
        ----------
        export_mode : ExportMode

        Returns
        -------
        dict

        """
        path = os.path.join(
            os.path.dirname(getattr(PyDSS, "__path__")[0]),
            "PyDSS",
            "defaults",
            "ExportLists",
            filename_from_enum(export_mode),
        )

        return load_data(path)

    def add_post_process(self, post_process_info):
        """Add a post-process script to a scenario.

        Parameters
        ----------
        post_process_info : dict
            Must define all fields in PyDssScenario.REQUIRED_POST_PROCESS_FIELDS

        """
        for field in self.REQUIRED_POST_PROCESS_FIELDS:
            if field not in post_process_info:
                raise InvalidParameter(
                    f"missing post-process field={field}"
                )
        config_file = post_process_info["config_file"]
        if not os.path.exists(config_file):
            raise InvalidParameter(f"{config_file} does not exist")

        self.post_process_infos.append(post_process_info)
        logger.info("Appended post-process script %s to %s",
                    post_process_info["script"], self.name)

def load_config(path):
    """Return a configuration from files.

    Parameters
    ----------
    path : str

    Returns
    -------
    dict

    """
    files = [os.path.join(path, x) for x in os.listdir(path) \
             if os.path.splitext(x)[1] == ".toml"]
    assert len(files) == 1, "only 1 .toml file is currently supported"
    return load_data(files[0])
