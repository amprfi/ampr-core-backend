from abc import ABC, abstractmethod
from typing import Protocol


class ModuleInterface(Protocol):
    """
    Protocol defining the interface that all third-party modules must implement.
    
    Modules are specialized agents that can be invoked via @mention syntax in user messages.
    They operate independently from core Ampr agents and return responses that are passed
    through the main chat agent.
    """
    
    name: str
    trigger: str
    
    async def invoke(self, message: str) -> str:
        """
        Process a user message and return a response.
        
        Args:
            message: The full user message (including the @mention trigger)
            
        Returns:
            The module's response as a string
            
        Raises:
            Exception: If the module fails to process the message
        """
        ...


class BaseModule(ABC):
    """
    Abstract base class for third-party modules.
    
    All modules should inherit from this class and implement the invoke method.
    """
    
    def __init__(self, name: str, trigger: str):
        self.name = name
        self.trigger = trigger
    
    @abstractmethod
    async def invoke(self, message: str) -> str:
        """
        Process a user message and return a response.
        
        Args:
            message: The full user message (including the @mention trigger)
            
        Returns:
            The module's response as a string
            
        Raises:
            Exception: If the module fails to process the message
        """
        pass
