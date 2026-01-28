"""Factory for creating model-specific data fetchers"""
from typing import Dict, Type

from app.services.base_data_fetcher import BaseDataFetcher
from app.services.nomads_data_fetcher import NOMADSDataFetcher
from app.models.model_registry import ModelRegistry, ModelProvider


class ModelFactory:
    """Factory for creating data fetchers for different models"""
    
    # Registry of fetcher classes by provider
    _fetchers: Dict[ModelProvider, Type[BaseDataFetcher]] = {
        ModelProvider.NOMADS: NOMADSDataFetcher,
        # Future providers can be added here:
        # ModelProvider.AWS: AWSDataFetcher,
        # ModelProvider.ECMWF: ECMWFDataFetcher,
    }
    
    @classmethod
    def create_fetcher(cls, model_id: str) -> BaseDataFetcher:
        """
        Create appropriate data fetcher for the given model.
        
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
        
        fetcher_class = cls._fetchers.get(model_config.provider)
        
        if not fetcher_class:
            raise ValueError(
                f"No fetcher available for provider: {model_config.provider.value}. "
                f"Available providers: {[p.value for p in cls._fetchers.keys()]}"
            )
        
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
