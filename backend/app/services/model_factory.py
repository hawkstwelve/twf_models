"""Factory for creating model-specific data fetchers"""
from typing import Dict, Type
import logging

from app.services.base_data_fetcher import BaseDataFetcher
from app.services.nomads_data_fetcher import NOMADSDataFetcher
from app.models.model_registry import ModelRegistry, ModelProvider

logger = logging.getLogger(__name__)


class ModelFactory:
    """Factory for creating data fetchers for different models"""
    
    # Registry of fetcher classes by provider (legacy mapping)
    _fetchers_by_provider: Dict[ModelProvider, Type[BaseDataFetcher]] = {
        ModelProvider.NOMADS: NOMADSDataFetcher,
        # Future providers can be added here:
        # ModelProvider.AWS: AWSDataFetcher,
        # ModelProvider.ECMWF: ECMWFDataFetcher,
    }
    
    # Registry of fetcher classes by fetcher_type (new flexible mapping)
    _fetchers_by_type: Dict[str, Type[BaseDataFetcher]] = {
        "nomads": NOMADSDataFetcher,
        # "herbie" will be added dynamically if available
    }
    
    @classmethod
    def _get_herbie_fetcher_class(cls):
        """Lazy import HerbieDataFetcher to avoid hard dependency"""
        try:
            from app.services.herbie_data_fetcher import HerbieDataFetcher
            return HerbieDataFetcher
        except ImportError:
            logger.warning("HerbieDataFetcher not available (herbie-data not installed)")
            return None
    
    @classmethod
    def create_fetcher(cls, model_id: str) -> BaseDataFetcher:
        """
        Create appropriate data fetcher for the given model.
        
        Routing logic (in priority order):
        1. If model.fetcher_type is set → use that fetcher
        2. Else if model.provider is set → use provider's default fetcher
        3. Else → error
        
        Args:
            model_id: Model identifier (e.g., "GFS", "AIGFS", "HRRR")
        
        Returns:
            BaseDataFetcher instance configured for the model
        
        Raises:
            ValueError: If model is unknown, disabled, or has no fetcher
        """
        model_config = ModelRegistry.get(model_id)
        
        if not model_config:
            raise ValueError(f"Unknown model: {model_id}")
        
        if not model_config.enabled:
            raise ValueError(f"Model {model_id} is not enabled")
        
        # Route 1: Explicit fetcher_type (new flexible approach)
        if model_config.fetcher_type:
            fetcher_type = model_config.fetcher_type.lower()
            
            # Special handling for Herbie (lazy load)
            if fetcher_type == "herbie":
                HerbieDataFetcher = cls._get_herbie_fetcher_class()
                if HerbieDataFetcher:
                    logger.info(f"Using HerbieDataFetcher for {model_id}")
                    return HerbieDataFetcher(model_id)
                else:
                    raise ValueError(
                        f"Model {model_id} configured for Herbie, but herbie-data not installed. "
                        f"Install with: pip install herbie-data"
                    )
            
            # Standard fetcher types
            fetcher_class = cls._fetchers_by_type.get(fetcher_type)
            if fetcher_class:
                logger.info(f"Using {fetcher_class.__name__} for {model_id} (fetcher_type={fetcher_type})")
                return fetcher_class(model_id)
            else:
                raise ValueError(
                    f"Unknown fetcher_type: {fetcher_type}. "
                    f"Available: {list(cls._fetchers_by_type.keys()) + ['herbie']}"
                )
        
        # Route 2: Legacy provider-based routing
        fetcher_class = cls._fetchers_by_provider.get(model_config.provider)
        
        if not fetcher_class:
            raise ValueError(
                f"No fetcher available for provider: {model_config.provider.value}. "
                f"Available providers: {[p.value for p in cls._fetchers_by_provider.keys()]}. "
                f"Or set fetcher_type explicitly in model config."
            )
        
        logger.info(f"Using {fetcher_class.__name__} for {model_id} (provider={model_config.provider.value})")
        return fetcher_class(model_id)
    
    @classmethod
    def register_fetcher(cls, provider: ModelProvider, fetcher_class: Type[BaseDataFetcher]):
        """
        Register a new fetcher class for a provider.
        
        This allows adding custom fetchers without modifying this file.
        
        Args:
            provider: ModelProvider enum value
            fetcher_class: BaseDataFetcher subclass
        """
        if not issubclass(fetcher_class, BaseDataFetcher):
            raise TypeError(f"{fetcher_class.__name__} must inherit from BaseDataFetcher")
        
        cls._fetchers[provider] = fetcher_class
    
    @classmethod
    def get_supported_providers(cls) -> list[ModelProvider]:
        """Get list of providers with registered fetchers"""
        return list(cls._fetchers.keys())
    
    @classmethod
    def supports_provider(cls, provider: ModelProvider) -> bool:
        """Check if a provider has a registered fetcher"""
        return provider in cls._fetchers
