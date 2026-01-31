"""
Variable Requirements Registry
Defines what raw and derived fields each map variable needs.
This is the SINGLE SOURCE OF TRUTH for the data pipeline.
"""
from typing import Dict, List, Set
from dataclasses import dataclass


@dataclass
class VariableRequirements:
    """Requirements for generating a map variable"""
    
    # Raw GRIB fields needed
    raw_fields: Set[str]
    
    # Derived fields that must be computed
    derived_fields: Set[str]
    
    # Optional fields (used if available)
    optional_fields: Set[str]
    
    # Whether this variable needs precipitation accumulation
    needs_precip_total: bool = False
    
    # Whether this variable needs snowfall accumulation
    needs_snow_total: bool = False
    
    # Whether this variable needs 6-hour precip rate
    needs_precip_6hr_rate: bool = False
    
    # Whether this requires upper air data
    needs_upper_air: bool = False
    
    # Whether this requires radar
    needs_radar: bool = False


class VariableRegistry:
    """Registry of variable requirements"""
    
    _requirements: Dict[str, VariableRequirements] = {
        
        "temp": VariableRequirements(
            raw_fields={"tmp2m"},
            derived_fields=set(),
            optional_fields={"prate"},  # For masking if desired
            needs_precip_total=False,
            needs_precip_6hr_rate=False,
        ),
        "temperature_2m": VariableRequirements(  # Alias for temp
            raw_fields={"tmp2m"},
            derived_fields=set(),
            optional_fields={"prate"},
            needs_precip_total=False,
            needs_precip_6hr_rate=False,
        ),
        
        "precip": VariableRequirements(
            raw_fields={"tp", "prate"},
            derived_fields={"tp_total"},  # Must compute 0→H accumulation
            optional_fields={"crain", "csnow", "cicep", "cfrzr"},
            needs_precip_total=True,
            needs_precip_6hr_rate=False,
        ),
        "precipitation": VariableRequirements(  # Alias for precip
            raw_fields={"tp", "prate"},
            derived_fields={"tp_total"},
            optional_fields={"crain", "csnow", "cicep", "cfrzr"},
            needs_precip_total=True,
            needs_precip_6hr_rate=False,
        ),
        
        "wind_speed": VariableRequirements(
            raw_fields={"ugrd10m", "vgrd10m"},
            derived_fields=set(),
            optional_fields={"u10", "v10"},  # AIGFS uses u10/v10 instead
            needs_precip_total=False,
            needs_precip_6hr_rate=False,
        ),
        "wind_speed_10m": VariableRequirements(  # Alias for wind_speed
            raw_fields={"ugrd10m", "vgrd10m"},
            derived_fields=set(),
            optional_fields={"u10", "v10"},  # AIGFS uses u10/v10 instead
            needs_precip_total=False,
            needs_precip_6hr_rate=False,
        ),
        
        "mslp_precip": VariableRequirements(
            raw_fields={"prmsl", "prate", "tp"},
            derived_fields={"p6_rate_mmhr"},  # 6-hour mean rate in mm/hr
            optional_fields={"gh_500", "gh_1000", "crain", "csnow", "cicep", "cfrzr"},
            needs_precip_total=False,
            needs_precip_6hr_rate=True,
        ),
        "mslp_pcpn": VariableRequirements(  # Alias for mslp_precip
            raw_fields={"prmsl", "prate", "tp"},
            derived_fields={"p6_rate_mmhr"},
            optional_fields={"gh_500", "gh_1000", "crain", "csnow", "cicep", "cfrzr"},
            needs_precip_total=False,
            needs_precip_6hr_rate=True,
        ),
        
        "temp_850_wind_mslp": VariableRequirements(
            raw_fields={"tmp_850", "ugrd_850", "vgrd_850", "prmsl"},
            derived_fields=set(),
            optional_fields=set(),
            needs_precip_total=False,
            needs_precip_6hr_rate=False,
            needs_upper_air=True,
        ),
        "850mb": VariableRequirements(  # Alias for temp_850_wind_mslp
            raw_fields={"tmp_850", "ugrd_850", "vgrd_850", "prmsl"},
            derived_fields=set(),
            optional_fields=set(),
            needs_precip_total=False,
            needs_precip_6hr_rate=False,
            needs_upper_air=True,
        ),
        
        "radar": VariableRequirements(
            raw_fields={"refc"},
            derived_fields=set(),
            optional_fields={"prate"},  # Fallback if no refc
            needs_precip_total=False,
            needs_precip_6hr_rate=False,
            needs_radar=True,
        ),
        
        "radar_reflectivity": VariableRequirements(
            raw_fields={"refc"},
            derived_fields=set(),
            optional_fields=set(),
            needs_precip_total=False,
            needs_precip_6hr_rate=False,
            needs_radar=True,
        ),
        
        "snowfall": VariableRequirements(
            raw_fields={"tp", "prate"},  # Base precip fields (always needed)
            derived_fields={"tp_snow_total"},  # Must compute 0→H snowfall accumulation
            optional_fields={"csnow", "tmp_850", "tmp2m", "t2m"},  # csnow for GFS, temps for AIGFS
            needs_precip_total=False,
            needs_snow_total=True,
            needs_precip_6hr_rate=False,
            needs_upper_air=True,  # AIGFS needs T850 for snow classification
        ),
    }
    
    @classmethod
    def get(cls, variable: str) -> VariableRequirements:
        """Get requirements for a variable"""
        return cls._requirements.get(variable)
    
    @classmethod
    def get_all_raw_fields(cls, variables: List[str]) -> Set[str]:
        """Get union of all raw fields needed for given variables"""
        fields = set()
        for var in variables:
            req = cls.get(var)
            if req:
                fields.update(req.raw_fields)
                fields.update(req.optional_fields)
        return fields
    
    @classmethod
    def needs_precip_total(cls, variables: List[str]) -> bool:
        """Check if any variable needs total precipitation"""
        return any(cls.get(v).needs_precip_total for v in variables if cls.get(v))
    
    @classmethod
    def needs_snow_total(cls, variables: List[str]) -> bool:
        """Check if any variable needs total snowfall"""
        return any(cls.get(v).needs_snow_total for v in variables if cls.get(v))
    
    @classmethod
    def needs_precip_6hr_rate(cls, variables: List[str]) -> bool:
        """Check if any variable needs 6-hour precip rate"""
        return any(cls.get(v).needs_precip_6hr_rate for v in variables if cls.get(v))
    
    @classmethod
    def filter_by_model_capabilities(cls, variables: List[str], model_config) -> List[str]:
        """Filter variables based on model capabilities"""
        filtered = []
        for var in variables:
            req = cls.get(var)
            if not req:
                continue
            
            # Check radar requirement
            if req.needs_radar and not model_config.has_refc:
                continue
            
            # Check upper air requirement
            if req.needs_upper_air and not model_config.has_upper_air:
                continue
            
            # Check exclusion list
            if var in model_config.excluded_variables:
                continue
            
            filtered.append(var)
        
        return filtered
