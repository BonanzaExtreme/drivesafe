"""Braking distance utilities using a dry-asphalt stopping model.

Model
-----
Total stopping distance is split into:

  d_total = d_reaction + d_braking

where:
  d_reaction = v * T_r
  d_braking  = v^2 / (2 * a_eff)

The effective deceleration is computed from dry-asphalt friction only:

  a_eff = μ * g
"""

from __future__ import annotations

from dataclasses import dataclass

GRAVITY_MPS2 = 9.81
DRY_ASPHALT_MU = 0.75


def kmh_to_mps(speed_kmh: float) -> float:
  """Convert speed from km/h to m/s."""
  return max(0.0, float(speed_kmh)) / 3.6


def effective_deceleration(
  mu: float = DRY_ASPHALT_MU,
) -> float:
  """Compute effective braking deceleration in m/s² on dry asphalt."""
  decel = mu * GRAVITY_MPS2
  return max(0.1, decel)


def reaction_distance(speed_mps: float, reaction_time_s: float = 1.5) -> float:
  """Distance traveled during driver/system reaction time."""
  speed = max(0.0, float(speed_mps))
  reaction_time = max(0.0, float(reaction_time_s))
  return speed * reaction_time


def braking_distance(
  speed_mps: float,
  mu: float = DRY_ASPHALT_MU,
) -> float:
  """Distance required to brake to full stop from `speed_mps`."""
  speed = max(0.0, float(speed_mps))
  decel = effective_deceleration(mu=mu)
  return (speed * speed) / (2.0 * decel)


@dataclass(frozen=True)
class BrakingModel:
  """Stopping-distance model configured for dry asphalt only."""

  reaction_time_s: float = 1.5
  safety_margin: float = 1.20
  mu: float = DRY_ASPHALT_MU

  def stopping_distance_m(self, speed_kmh: float) -> float:
    """Total stopping distance in meters for speed in km/h."""
    speed_mps = kmh_to_mps(speed_kmh)
    d_react = reaction_distance(speed_mps, self.reaction_time_s)
    d_brake = braking_distance(speed_mps, self.mu)
    base_total = d_react + d_brake
    return base_total * max(1.0, float(self.safety_margin))

  def danger_for_distance(self, object_distance_m: float, speed_kmh: float) -> bool:
    """True when object is inside computed stopping distance."""
    return float(object_distance_m) < self.stopping_distance_m(speed_kmh)


def is_danger_distance(
  object_distance_m: float,
  speed_kmh: float,
  reaction_time_s: float = 1.5,
  safety_margin: float = 1.20,
) -> bool:
  """Convenience API to evaluate danger using dry-asphalt stopping distance."""
  model = BrakingModel(
    reaction_time_s=reaction_time_s,
    safety_margin=safety_margin,
  )
  return model.danger_for_distance(object_distance_m, speed_kmh)

