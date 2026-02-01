"""Base class for grid locator strategies."""

from abc import ABC, abstractmethod
from typing import Dict, List
import xarray as xr


class GridLocator(ABC):
    """Abstract base class for grid location strategies."""
    
    @abstractmethod
    def sample(self, ds: xr.Dataset, variable: str, 
               stations: List['Station']) -> Dict[str, float]:
        """
        Extract model values at station locations.
        
        Args:
            ds: xarray Dataset with forecast data
            variable: Variable name to sample
            stations: List of Station objects with lat/lon
        
        Returns:
            Dictionary mapping station IDs to extracted values
        """
        pass
    
    @classmethod
    @abstractmethod
    def can_handle(cls, ds: xr.Dataset) -> bool:
        """
        Check if this locator can handle the given dataset.
        
        Args:
            ds: xarray Dataset to check
        
        Returns:
            True if this locator can sample from this dataset
        """
        pass
