"""Engineer Dzyaloshinskii-Moriya exchange on a 4-site ring with local z pulses.

Reference: N. Nishad, A. Keselman, T. Lahaye, A. Browaeys and S. Tsesses,
"Quantum simulation of generic spin-exchange models in Floquet-engineered
Rydberg-atom arrays", Phys. Rev. A 108, 053318 (2023),
doi:10.1103/PhysRevA.108.053318. The target is their Eq. (8) at J = 0, the
pure out-of-plane DM ring of their Fig. 2(c):
D sum_i (X_i Y_{i+1} - Y_i X_{i+1}), bonds oriented i -> i+1, wrap included.

The native interaction is their Eq. (1), XX + YY exchange. Local z rotations
(their Fig. 2(a)) toggle it between three frames: +XY, pure DM, and -XY,
with dwells t_J, t_D and t_-J. Ideally (zero-width pulses) the DM per bond is
the native exchange times t_D / T, with the XY parts cancelling when
t_J = t_-J. Here the native carries 1.0 per bond (``NearestNeighbor(0.5)``
on a symmetric op string counts both orientations) and the target 0.5, so
the ideal point is t_D = T/2, t_J = t_-J = T/4, inside the dwell range. Each
sequence is [N, +DM, N, +XX, N] followed by its time reverse, which the
optimizer trims (dwell times and angles) onto the target unitary.

Three variants, each a function that trains and returns its result. Final
gate infidelities over seeds 0-4 (100 epochs, 2026-10-14):

- ``antisymmetric_xx_floquet``: NN exchange, instantaneous rotations, the
  paper's model. 5.2e-8 .. 5.5e-8.
- ``antisymmetric_dipolar_xx``: dipolar 1/r^3 exchange, whose r = 2 tail
  (1/8, the paper's Appendix F) the patterns were not designed for. 4.6e-7
  .. 4.7e-7.
- ``antisymmetric_dipolar_xx_finite_pulses``: the dipolar case with each
  rotation replaced by a finite z-field pulse of width ``tau_p`` that
  co-evolves with the exchange (the paper's practical case), in a plain
  ``FloquetSequence``. 1.146e-4 .. 1.154e-4 at ``tau_p = 0.05``.

Each trains in about 5-10 s on CPU.
"""

from collections.abc import Callable

import torch
from doqs.common.operators.operator import Operator
from doqs.common.operators.rotation import Rotation
from doqs.common.primitives.graph import Graph
from doqs.common.pulses import Lattice, NearestNeighbor, PowerLaw
from doqs.common.pulses.finite_pulse import make_finite_pulse_block
from doqs.common.sequence.floquet_sequence import FloquetSequence
from doqs.common.training import OptimizationResult
from doqs.floqtimizer.floqtimizer_trainer import FloqtimizerTrainer, TrainingConfig

NUM_SITES = 4
SPIN = 0.5
PBC = True
RING = Lattice("square", NUM_SITES, 1, PBC)
# Per-site z angles of the two rotations, theta[s] on site s. Rz(DM_PATTERN)
# turns the native exchange into +2x the target (D > 0, the paper's sign);
# the opposite-sign pattern gives -2x, which no dwell times can undo.
DM_PATTERN = [0, -torch.pi / 2, -torch.pi, -3 * torch.pi / 2]
XX_PATTERN = [-torch.pi, torch.pi / 2, 0, 3 * torch.pi / 2]


def _config(max_epochs: int) -> TrainingConfig:
    """The full-rank AdamW config every variant trains with."""
    return TrainingConfig(
        max_epochs=max_epochs,
        num_cycles_per_period=1,
        optimizer="AdamW",
        learning_rate=3e-3,
        phase_learning_rate=3e-3,
        rank="full",
        eval_rank="full",
        eval_seed=0,
        eval_chunk_size=256,
        device="cpu",
        progress=True,
        steps_per_epoch=10,
        check_val_every_n_epoch=5,
    )


def _dipolar() -> PowerLaw:
    return PowerLaw(0.5, alpha=3)


def _dm_target() -> Graph:
    """Nishad et al. Eq. (8) at J = 0, D = 0.5: every variant's target.

    0.5 sum_i (X_i Y_{i+1} - Y_i X_{i+1}), i+1 mod N.

    The asymmetric op strings orient every bond along +1, the wrap bond
    N-1 -> 0 included (see ``doqs.common.pulses.coupling``).
    """
    return Graph(RING, [("XY", NearestNeighbor(0.5)), ("YX", NearestNeighbor(-0.5))])


def _z_rotation(pattern: list[float]) -> Rotation:
    return Rotation(
        spin_op="z",
        theta=pattern,
        trainable=True,
        num_sites=None,
        spin=None,
        n_aux=None,
        excitation_number=None,
    )


def _nn_native() -> Operator:
    return Operator(
        Graph(RING, [("XX", NearestNeighbor(0.5)), ("YY", NearestNeighbor(0.5))]),
        spin=SPIN,
        n_aux=0,
        backend="dense",
        excitation_number=None,
    )


def _dipolar_native() -> Operator:
    """The dipolar XX + YY exchange as one dense block."""
    return Operator(
        Graph(RING, [("XX", _dipolar()), ("YY", _dipolar())]),
        spin=SPIN,
        backend="dense",
        n_aux=0,
        excitation_number=None,
    )


def _half_sequence(
    make_native: Callable[[], Operator], rotation_a: Operator, rotation_b: Operator
) -> list[Operator]:
    """[N, +DM, N, +XX, N]: a fresh native block between and around the rotations."""
    return [make_native(), rotation_a, make_native(), rotation_b, make_native()]


def _train_floquet(
    half_sequence: list[Operator], name: str, max_epochs: int
) -> OptimizationResult:
    """Train [N, +DM, N, +XX, N] plus its mirror onto the DM target."""
    # FloquetSequence appends the mirror [N, -XX, N, -DM, N] itself.
    control_sequence = FloquetSequence(
        half_sequence,
        num_sites=NUM_SITES,
        spin=SPIN,
        n_aux=0,
        operator_cache=None,
        rtol=1e-10,
        atol=1e-10,
        excitation_number=None,
    )
    config = _config(max_epochs=max_epochs)
    # Unit native-interaction budget; the caller owns the period.
    control_sequence.set_period(1.0 / config.num_cycles_per_period)
    trainer = FloqtimizerTrainer(
        control_sequence, _dm_target(), config, build_graph=True, experiment_name=name
    )
    return trainer.train()


def antisymmetric_xx_floquet() -> OptimizationResult:
    """NN XX + YY exchange -> NN DM exchange, instantaneous rotations."""
    return _train_floquet(
        _half_sequence(_nn_native, _z_rotation(DM_PATTERN), _z_rotation(XX_PATTERN)),
        "antisymmetric_xx_floquet",
        max_epochs=100,
    )


def antisymmetric_dipolar_xx() -> OptimizationResult:
    """Dipolar XX + YY exchange -> NN DM exchange, instantaneous rotations."""
    return _train_floquet(
        _half_sequence(
            _dipolar_native, _z_rotation(DM_PATTERN), _z_rotation(XX_PATTERN)
        ),
        "antisymmetric_dipolar_xx",
        max_epochs=100,
    )


def antisymmetric_dipolar_xx_finite_pulses(
    tau_p: float, max_epochs: int
) -> OptimizationResult:
    """The dipolar sequence with each rotation a finite z-field pulse.

    Each pulse block evolves H = 0.5 (XX + YY)_dipolar + sum_l h_l Z_l for
    ``tau_p``, with h_l = theta_l / tau_p, so it approaches the ideal
    Rz(theta_l) as ``tau_p`` -> 0. The trainable variable is theta_l (O(1))
    rather than h_l, so gradients stay O(1) whatever ``tau_p`` is. The mirror
    runs each pulse with -h_l and leaves the exchange alone. ``set_period(1)``
    holds the pulses at ``tau_p`` and shares the rest equally among the
    natives, 6 t_native + 4 tau_p = 1.

    tau_p sweep (100 epochs, seed 0, 2026-10-14)::

        tau_p | final loss
        1e-3  | 5.2e-07
        0.01  | 5.1e-06
        0.05  | 1.1e-04
        0.1   | 4.4e-04

    The loss falls roughly in proportion to ``tau_p``. The previous explicit
    9-block build, which could not mirror the pulse fields, gave 1.2e-4 at
    0.05 and 2.8e-5 at 0.01.
    """

    def make_pulse(thetas: list[float]) -> Operator:
        return make_finite_pulse_block(
            lattice=RING,
            spin=SPIN,
            thetas=thetas,
            tau_p=tau_p,
            native_coupling=_dipolar(),
            trainable=True,
            backend="dense",
        )

    return _train_floquet(
        _half_sequence(_dipolar_native, make_pulse(DM_PATTERN), make_pulse(XX_PATTERN)),
        "antisymmetric_dipolar_xx_finite_pulses",
        max_epochs=max_epochs,
    )


if __name__ == "__main__":
    for result in (
        antisymmetric_xx_floquet(),
        antisymmetric_dipolar_xx(),
        antisymmetric_dipolar_xx_finite_pulses(tau_p=0.05, max_epochs=100),
    ):
        print(f"{result.method}: final loss {result.final_loss:.3e}")
