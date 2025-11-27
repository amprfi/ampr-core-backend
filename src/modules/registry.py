import re
import yaml
import logging
from pathlib import Path
from typing import Optional, Dict, List
from importlib import import_module

from .base import ModuleInterface

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """
    Registry for managing third-party modules.
    
    Handles module discovery, registration, and invocation based on @mention triggers.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.modules: Dict[str, ModuleInterface] = {}
        self.triggers: Dict[str, str] = {}
        
        if config_path is None:
            config_path = str(Path(__file__).parent / "modules.yaml")
        
        self.config_path = config_path
        self._load_modules()
    
    def _load_modules(self):
        """Load modules from configuration file."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            if not config or 'modules' not in config:
                logger.warning(f"No modules defined in {self.config_path}")
                return
            
            for module_config in config['modules']:
                if not module_config.get('enabled', True):
                    logger.info(f"Skipping disabled module: {module_config.get('name')}")
                    continue
                
                self._register_module(
                    name=module_config['name'],
                    trigger=module_config['trigger'],
                    path=module_config['path']
                )
            
            logger.info(f"Loaded {len(self.modules)} module(s) from registry")
            
        except FileNotFoundError:
            logger.warning(f"Module config file not found: {self.config_path}")
        except Exception as e:
            logger.error(f"Error loading modules: {str(e)}", exc_info=True)
    
    def _register_module(self, name: str, trigger: str, path: str):
        """
        Register a single module.
        
        Args:
            name: Module name
            trigger: Trigger string (e.g., "@defianalyst")
            path: Python import path (e.g., "src.modules.defianalyst")
        """
        try:
            module = import_module(f"{path}.agent")
            
            factory_func = getattr(module, f"get_{name}_module", None)
            if not factory_func:
                logger.error(f"Module {name} missing factory function: get_{name}_module")
                return
            
            instance = factory_func()
            
            self.modules[name] = instance
            self.triggers[trigger] = name
            
            logger.info(f"Registered module: {name} with trigger: {trigger}")
            
        except Exception as e:
            logger.error(f"Failed to register module {name}: {str(e)}", exc_info=True)
    
    def detect_module_trigger(self, message: str) -> Optional[str]:
        """
        Detect if a message contains a module trigger.
        
        Args:
            message: User message to scan for triggers
            
        Returns:
            Module name if trigger found, None otherwise
        """
        for trigger, module_name in self.triggers.items():
            if trigger in message:
                logger.info(f"Detected trigger '{trigger}' for module '{module_name}'")
                return module_name
        
        return None
    
    def get_module(self, name: str) -> Optional[ModuleInterface]:
        """
        Get a registered module by name.
        
        Args:
            name: Module name
            
        Returns:
            Module instance or None if not found
        """
        return self.modules.get(name)
    
    async def invoke_module(self, name: str, message: str) -> str:
        """
        Invoke a module by name with the given message.
        
        Args:
            name: Module name
            message: User message to process
            
        Returns:
            Module response
            
        Raises:
            Exception: If module not found or invocation fails
        """
        module = self.get_module(name)
        if not module:
            raise Exception(f"Module '{name}' not found in registry")
        
        logger.info(f"Invoking module: {name}")
        return await module.invoke(message)
    
    def list_modules(self) -> List[Dict[str, str]]:
        """
        List all registered modules.
        
        Returns:
            List of dictionaries with module info (name, trigger)
        """
        return [
            {"name": module.name, "trigger": module.trigger}
            for module in self.modules.values()
        ]


_registry_instance: Optional[ModuleRegistry] = None


def get_module_registry() -> ModuleRegistry:
    """
    Get the singleton module registry instance.
    
    Returns:
        ModuleRegistry instance
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ModuleRegistry()
    return _registry_instance
