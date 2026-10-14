"""Engineer a purely next-nearest-neighbour XX+YY chain from dipolar exchange.

Four spin-1/2 atoms sit in an open line and interact by native dipolar exchange
J(r) (XX + YY) with J(r) = 1 / r^3. A z-rotation by pi on every other site flips
the sign of every bond joining sites of opposite parity, i.e. every odd-distance
bond. Evolving half the period before the flip and half after therefore cancels
the r = 1 and r = 3 bonds and keeps the r = 2 bonds at their native 1/8: the
target is NNN XX + YY at strength 1/8 with no NN term.

The chain is open because that is the geometry where the target is well posed.
On a 4-site ring the r = 3 bond becomes a second NN bond, and the r = 2 pair is
its own periodic image (N - r = r), so its strength depends on whether the
images are summed (2/8) or the minimum image is kept (1/8); the open chain has
one distance per pair and no such convention to choose.

Expected outcome: the optimizer trims the dwell times and the flip angles to a
final gate infidelity of ~4e-6 within 100 epochs (about 5 s on CPU; measured
2026-10-13 over five seeds, which agree to within 10%).
"""

import copy

import torch
from doqs.common.operators.operator import Operator
from doqs.common.operators.rotation import Rotation
from doqs.common.primitives.graph import Graph
from doqs.common.pulses import DisplacementCoupling, Lattice, PowerLaw
from doqs.common.sequence.floquet_sequence import FloquetSequence
from doqs.common.training import OptimizationResult
from doqs.floqtimizer.floqtimizer_trainer import FloqtimizerTrainer, TrainingConfig


def nnn_xx_open_chain() -> OptimizationResult:
    """Train the half-period, pi-flip Floquet sequence onto NNN XX + YY at 1/8."""
    num_sites = 4
    spin = 0.5
    chain = Lattice("square", num_sites, 1, False)

    native_operator = Operator(
        Graph(chain, [("XX", PowerLaw(1.0, alpha=3)), ("YY", PowerLaw(1.0, alpha=3))]),
        spin=None,
        backend="dense",
        n_aux=None,
        excitation_number=None,
    )
    # [0, pi] tiles to [0, pi, 0, pi]: the parity flip.
    parity_flip = Rotation(
        spin_op="z",
        theta=[0, torch.pi],
        trainable=True,
        num_sites=None,
        spin=None,
        n_aux=None,
        excitation_number=None,
    )
    # FloquetSequence appends the time-reversed half itself.
    control_sequence = FloquetSequence(
        [native_operator, parity_flip, copy.deepcopy(native_operator)],
        num_sites=num_sites,
        spin=spin,
        n_aux=0,
        operator_cache=None,
        rtol=1e-10,
        atol=1e-10,
        excitation_number=None,
    )
    target_graph = Graph(
        chain,
        [
            ("XX", DisplacementCoupling({(2, 0): 1 / 8.0})),
            ("YY", DisplacementCoupling({(2, 0): 1 / 8.0})),
        ],
    )
    config = TrainingConfig(
        max_epochs=100,
        optimizer="AdamW",
        num_cycles_per_period=2,
        learning_rate=1e-3,
        phase_learning_rate=1e-3,
        rank=0.2,
        eval_rank="full",
        eval_seed=0,
        eval_chunk_size=256,
        device="cpu",
        progress=True,
        steps_per_epoch=10,
        check_val_every_n_epoch=5,
    )
    # Unit native-interaction budget; the caller owns the period.
    control_sequence.set_period(1.0 / config.num_cycles_per_period)

    trainer = FloqtimizerTrainer(
        control_sequence,
        target_graph,
        config,
        build_graph=True,
        experiment_name="nnn_xx_open_chain",
    )
    return trainer.train()


if __name__ == "__main__":
    print(f"final loss: {nnn_xx_open_chain().final_loss:.3e}")
