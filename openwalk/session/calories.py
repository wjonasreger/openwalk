"""Calorie calculation using LCDA Walking Equation and Mifflin-St Jeor BMR.

References:
    - Looney DP et al. "Metabolic Costs of Standing and Walking in Healthy
      Military-Age Adults: A Meta-regression." Med Sci Sports Exerc. 2019.
    - Mifflin MD, St Jeor ST et al. "A new predictive equation for resting
      energy expenditure in healthy individuals." Am J Clin Nutr. 1990.
"""

from dataclasses import dataclass

# 1 watt = 60 J/min, 1 kcal = 4184 J => 1 W = 60/4184 kcal/min
WATTS_TO_KCAL_MIN = 0.01434

# Standing metabolic cost from LCDA equation (W/kg)
STANDING_METABOLIC_COST = 1.44

# Minutes per day (for BMR conversion)
MINUTES_PER_DAY = 1440


@dataclass(frozen=True)
class UserProfile:
    """User physical profile for calorie calculations."""

    weight_lbs: float = 275.0
    height_inches: float = 67.0
    age_years: int = 29
    gender: str = "male"

    @property
    def weight_kg(self) -> float:
        return self.weight_lbs * 0.453592

    @property
    def height_cm(self) -> float:
        return self.height_inches * 2.54


def gross_metabolic_rate_wpkg(speed_mph: float) -> float:
    """Calculate gross metabolic rate using LCDA Walking Equation.

    Formula: M = 1.44 + 1.94 * S^0.43 + 0.24 * S^4
    where S = speed in m/s.

    Args:
        speed_mph: Walking speed in miles per hour.

    Returns:
        Metabolic rate in watts per kilogram.
    """
    if speed_mph <= 0:
        return STANDING_METABOLIC_COST

    speed_ms = speed_mph * 0.44704
    result: float = 1.44 + 1.94 * (speed_ms**0.43) + 0.24 * (speed_ms**4)
    return result


def gross_kcal_per_min(speed_mph: float, profile: UserProfile) -> float:
    """Calculate gross energy expenditure in kcal/min.

    Args:
        speed_mph: Walking speed in miles per hour.
        profile: User physical profile.

    Returns:
        Gross kcal/min at given speed.
    """
    return gross_metabolic_rate_wpkg(speed_mph) * profile.weight_kg * WATTS_TO_KCAL_MIN


def bmr_kcal_per_min(profile: UserProfile) -> float:
    """Calculate BMR in kcal/min using Mifflin-St Jeor equation.

    Male:   BMR = (10 * kg) + (6.25 * cm) - (5 * age) + 5
    Female: BMR = (10 * kg) + (6.25 * cm) - (5 * age) - 161

    Args:
        profile: User physical profile.

    Returns:
        BMR in kilocalories per minute.
    """
    base = (10 * profile.weight_kg) + (6.25 * profile.height_cm) - (5 * profile.age_years)
    bmr = base + 5 if profile.gender.lower() == "male" else base - 161
    return bmr / MINUTES_PER_DAY


def net_kcal_per_min(speed_mph: float, profile: UserProfile) -> float:
    """Calculate net kcal/min above resting baseline.

    Args:
        speed_mph: Walking speed in miles per hour.
        profile: User physical profile.

    Returns:
        Net energy expenditure in kcal/min (always >= 0).
    """
    return max(0.0, gross_kcal_per_min(speed_mph, profile) - bmr_kcal_per_min(profile))
