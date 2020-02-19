"""Contains functionality to configure PyDSS simulations."""

import enum
import logging
import os

import PyDSS
from PyDSS.exceptions import InvalidParameter
from PyDSS.pyDSS import instance
from PyDSS.utils.utils import dump_data, load_data


logger = logging.getLogger(__name__)


class ControllerType(enum.Enum):
    PV_CONTROLLER = "PvController"
    SOCKET_CONTROLLER = "SocketController"
    STORAGE_CONTROLLER = "StorageController"
    XMFR_CONTROLLER = "xmfrController"


CONTROLLER_TYPES = tuple(x.value for x in ControllerType)
CONFIG_EXT = ".toml"


class ExportMode(enum.Enum):
    BY_CLASS = "ExportMode-byClass"
    BY_ELEMENT = "ExportMode-byElement"


def _filename_from_enum(obj):
    return obj.value + CONFIG_EXT


PV_CONTROLLER_FILENAME = _filename_from_enum(ControllerType.PV_CONTROLLER)
STORAGE_CONTROLLER_FILENAME = _filename_from_enum(ControllerType.STORAGE_CONTROLLER)
SOCKET_CONTROLLER_FILENAME = _filename_from_enum(ControllerType.XMFR_CONTROLLER)
XMFR_CONTROLLER_FILENAME = _filename_from_enum(ControllerType.SOCKET_CONTROLLER)
EXPORT_BY_CLASS_FILENAME = _filename_from_enum(ExportMode.BY_CLASS)
EXPORT_BY_ELEMENT_FILENAME = _filename_from_enum(ExportMode.BY_ELEMENT)
PLOTS_FILENAME = "plots.toml"
SIMULATION_SETTINGS_FILENAME = "simulation.toml"

DEFAULT_SIMULATION_SETTINGS_FILE = os.path.join(
    os.path.dirname(getattr(PyDSS, "__path__")[0]),
    "PyDSS",
    "defaults",
    SIMULATION_SETTINGS_FILENAME,
)
DEFAULT_CONTROLLER_CONFIG_FILE = os.path.join(
    os.path.dirname(getattr(PyDSS, "__path__")[0]),
    "PyDSS",
    "defaults",
    "pyControllerList",
    PV_CONTROLLER_FILENAME,
)
DEFAULT_PLOT_SETTINGS_FILE = os.path.join(
    os.path.dirname(getattr(PyDSS, "__path__")[0]),
    "PyDSS",
    "defaults",
    "pyPlotList",
    PLOTS_FILENAME
)
DEFAULT_EXPORT_BY_CLASS_SETTINGS_FILE = os.path.join(
    os.path.dirname(getattr(PyDSS, "__path__")[0]),
    "PyDSS",
    "defaults",
    "ExportLists",
    EXPORT_BY_CLASS_FILENAME,
)
DEFAULT_EXPORT_BY_ELEMENT_SETTINGS_FILE = os.path.join(
    os.path.dirname(getattr(PyDSS, "__path__")[0]),
    "PyDSS",
    "defaults",
    "ExportLists",
    EXPORT_BY_ELEMENT_FILENAME,
)

DEFAULT_CONTROLLER_CONFIG = load_data(DEFAULT_CONTROLLER_CONFIG_FILE)
DEFAULT_PYDSS_SIMULATION_CONFIG = load_data(DEFAULT_SIMULATION_SETTINGS_FILE)
DEFAULT_PLOT_CONFIG = load_data(DEFAULT_PLOT_SETTINGS_FILE)
DEFAULT_EXPORT_BY_CLASS = load_data(DEFAULT_EXPORT_BY_CLASS_SETTINGS_FILE)
DEFAULT_EXPORT_BY_ELEMENT = load_data(DEFAULT_EXPORT_BY_ELEMENT_SETTINGS_FILE)


class PyDssProject:
    """Represents the project options for a PyDSS simulation."""

    _SCENARIOS = "Scenarios"
    _PROJECT_DIRECTORIES = ("DSSfiles", "Exports", "Logs", "Scenarios")

    def __init__(self, path, name, scenarios, simulation_config):
        self._name = name
        self._scenarios = scenarios
        self._simulation_config = simulation_config
        self._project_dir = os.path.join(path, self._name)
        self._scenarios_dir = os.path.join(self._project_dir, self._SCENARIOS)
        self._dss_dir = os.path.join(self._project_dir, "DSSfiles")

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

        raise InvalidParameter(f"{scenario} is not a valid scenario")
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

        raise InvalidParameter(f"{scenario} is not a valid scenario")

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
        for name in self._PROJECT_DIRECTORIES:
            os.makedirs(os.path.join(self._project_dir, name), exist_ok=True)

        self._serialize_scenarios()

        dump_data(
            self._simulation_config,
            os.path.join(self._project_dir, SIMULATION_SETTINGS_FILENAME),
        )


        logger.info("Initialized directories in %s", self._project_dir)

    @classmethod
    def create_project(cls, path, name, scenarios, simulation_config=None,
                       options=None):
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

        project = cls(path, name, scenarios, simulation_config)
        project.serialize()
        sc_names = [x.name for x in project.scenarios]
        logger.info("Created project=%s with scenarios=%s at %s", name,
                    sc_names, path)
        return project

    def run(self, logging_configured=True):
        """Run all scenarios in the project."""
        inst = instance()
        self._simulation_config["Logging"]["Pre-configured logging"] = logging_configured
        for scenario in self._scenarios:
            self._simulation_config["Project"]["Active Scenario"] = scenario.name
            inst.run(self._simulation_config, self, scenario)

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

    @staticmethod
    def load_simulation_config(project_path):
        """Return the simulation settings for a project, using defaults if the
        file is not defined.

        Parameters
        ----------
        project_path : str

        Returns
        -------
        dict

        """
        filename = os.path.join(project_path, SIMULATION_SETTINGS_FILENAME)
        if not os.path.exists(filename):
            filename = os.path.join(
                project_path,
                DEFAULT_SIMULATION_SETTINGS_FILE,
            )
            assert os.path.exists(filename)

        return load_data(filename)

    @classmethod
    def load_project(cls, path, options=None):
        """Load a PyDssProject from directory.

        Parameters
        ----------
        path : str
            full path to existing project
        options : dict
            options that override the config file

        """
        name = os.path.basename(path)
        simulation_config = load_data(
            os.path.join(path, SIMULATION_SETTINGS_FILENAME)
        )
        if options is not None:
            for category, params in options.items():
                if category not in simulation_config:
                    simulation_config[category] = {}
                simulation_config[category].update(params)
            logger.info("Overrode config options: %s", options)

        scenarios_dir = os.path.join(path, PyDssProject._SCENARIOS)
        scenario_names = set(
            [x for x in os.listdir(scenarios_dir)
             if os.path.isdir(os.path.join(scenarios_dir, x))]
        )

        if len(scenario_names) != len(simulation_config["Project"]["Scenarios"]):
            raise InvalidParameter(
                "mismatch between scenarios in the config file vs directories "
                "in project"
            )

        names = [x["name"] for x in simulation_config["Project"]["Scenarios"]]
        for scenario_name in names:
            if scenario_name not in scenario_names:
                raise InvalidParameter(
                    f"scenario {scenario_name} does not have a directory"
                )

        scenarios = [
            PyDssScenario.deserialize(
                os.path.join(scenarios_dir, x["name"]),
                post_process_infos=x["post_process_infos"],
            )
            for x in simulation_config["Project"]["Scenarios"]
        ]

        return PyDssProject(os.path.dirname(path), name, scenarios, simulation_config)

    @classmethod
    def run_project(cls, path, options=None):
        """Load a PyDssProject from directory and run all scenarios.

        Parameters
        ----------
        path : str
            full path to existing project
        options : dict
            options that override the config file

        """
        project = cls.load_project(path, options=options)
        return project.run()


class PyDssScenario:
    """Represents a PyDSS Scenario."""

    DEFAULT_CONTROLLER_TYPES = (ControllerType.PV_CONTROLLER,)
    DEFAULT_EXPORT_MODE = ExportMode.BY_CLASS
    _SCENARIO_DIRECTORIES = (
        "ExportLists",
        "pyControllerList",
        "pyPlotList",
        "PostProcess"
    )
    REQUIRED_POST_PROCESS_FIELDS = ("script", "config_file")

    def __init__(self, name, controller_types=None, controllers=None,
                 export_modes=None, exports=None, plots=None,
                 post_process_infos=None):
        self.name = name
        self.post_process_infos = []
        if controller_types is not None and controllers is not None:
            raise InvalidParameter(
                "controller_types and controllers cannot both be set"
            )
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

        if plots is None:
            self.plots = DEFAULT_PLOT_CONFIG
        elif isinstance(plots, str):
            self.plots = load_data(plots)
        else:
            self.plots = plots

        if post_process_infos is not None:
            for pp_info in post_process_infos:
                self.add_post_process(pp_info)

    @classmethod
    def deserialize(cls, path, post_process_infos):
        """Deserialize a PyDssScenario from a path.

        Parameters
        ----------
        path : str
            full path to scenario
        post_process_infos : list
            list of post_process_info dictionaries

        Returns
        -------
        PyDssScenario

        """
        name = os.path.basename(path)
        controllers = {}
        for filename in os.listdir(os.path.join(path, "pyControllerList")):
            base, ext = os.path.splitext(filename)
            if ext == ".toml":
                controller_type = ControllerType(base)
                controllers[controller_type] = load_data(
                    os.path.join(path, "pyControllerList", filename)
                )

        exports = {}
        for filename in os.listdir(os.path.join(path, "ExportLists")):
            base, ext = os.path.splitext(filename)
            if ext == ".toml":
                export_mode = ExportMode(base)
                exports[export_mode] = load_data(
                    os.path.join(path, "ExportLists", filename)
                )

        plots = load_config(os.path.join(path, "pyPlotList"))
        return cls(
            name,
            controllers=controllers,
            exports=exports,
            plots=plots,
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
            dump_data(
                controllers,
                os.path.join(path, "pyControllerList", _filename_from_enum(controller_type)),
            )

        for mode, exports in self.exports.items():
            dump_data(
                exports,
                os.path.join(path, "ExportLists", _filename_from_enum(mode))
            )

        dump_data(
            self.plots,
            os.path.join(path, "pyPlotList", PLOTS_FILENAME)
        )

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
            _filename_from_enum(controller_type),
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
            _filename_from_enum(export_mode),
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
