"""Factory for creating appropriate grid locator strategies."""

import logging
import xarray as xr
from .grid_locators import (
    GridLocator,
    LatLon1DLocator,
    ProjectedXYLocator,
    CurvilinearKDTreeLocator
)

logger = logging.getLogger(__name__)


class GridLocatorFactory:
    """Factory for creating appropriate grid locator based on dataset structure."""
    
    @staticmethod
    def from_dataset(ds: xr.Dataset) -> GridLocator:
        """
        Create appropriate grid locator for dataset.
        
        Args:
            ds: xarray Dataset to analyze
        
        Returns:
            GridLocator instance appropriate for this dataset
        
        Raises:
            ValueError: If no suitable locator found
        """
        # Try in priority order (fastest to slowest)
        if LatLon1DLocator.can_handle(ds):
            logger.debug("Using LatLon1DLocator (regular grid)")
            return LatLon1DLocator()
        
        elif ProjectedXYLocator.can_handle(ds):
            logger.debug("Using ProjectedXYLocator (projected rectilinear)")
            return ProjectedXYLocator()
        
        elif CurvilinearKDTreeLocator.can_handle(ds):
            logger.debug("Using CurvilinearKDTreeLocator (curvilinear fallback)")
            return CurvilinearKDTreeLocator()
        
        else:
            raise ValueError(
                "No suitable grid locator for dataset. "
                "Dataset must have either: 1D lat/lon, 1D x/y, or 2D lat/lon coords."
            )
