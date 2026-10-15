# hexgen digest — 2026-10-15

**2** new backlog item(s) in the last 7 day(s).

## New this window

- **Two rule-based detectors (graph-wire-search on the B-Rep face-adjacency graph; multi-vi...** · score 0.019
  - _Contributions:_ The paper introduces two task-specific rule-based hole detectors and a human-annotated real-world benchmark of engineering CAD parts. It runs a systematic study of accuracy, dataset-size sensitivity, IoU thresholds and cross-domain generalisation, finding rule-based methods generalise without training data while learning-based B-Rep networks degrade under domain shift.
  - _Applicable to our work:_ Evidence for the domain-gap care-area: B-Rep graph networks (esp. AAGNet) trained on one CAD source collapse on another, so hexgen's synthetic-to-real gap needs explicit testing. Rule-based hole/wire-loop detection on the face-adjacency graph could serve as cheap geometric checks or auxiliary features, and the real annotated CAD dataset is a candidate eval source.
  - _Additional context:_ Not program synthesis; value is as domain-shift evidence and B-Rep graph tooling. Dataset release status not confirmed in the text read.
  - _Impact_ 0.30 · _Applicability_ 0.42 · _Confidence_ 0.46 · _Effort_ 3.0/10
  [2610.13466](https://arxiv.org/abs/2610.13466)
- **A local iterative generator for degree-based PD-equivalent graphs, and a global constra...** · score 0.002
  - _Contributions:_ Introduces two methods for generating graphs that exactly match a target persistence diagram: a provably correct and complete local generator for degree filtrations, and a global constraint-satisfaction formulation that avoids the local approach's diversity/infeasibility trade-off. Both realize the target PD exactly on four standard graph generation benchmarks.
  - _Applicable to our work:_ Tangential: the idea of recasting hard structural validity requirements as a complete constraint-programming encoding could inspire exact/constraint-based repair or validity-guaranteed completion of face-graph topology in generated programs; not a direct fit for autoregressive decoding.
  - _Additional context:_ Non-neural, graph-topology (persistent homology) focus; weak bridge. Scalability of CP encoding to program-level constraints unclear.
  - _Impact_ 0.12 · _Applicability_ 0.18 · _Confidence_ 0.68 · _Effort_ 7.0/10
  [2610.18856](https://arxiv.org/abs/2610.18856)

## Current top 10 backlog

1. **Discovery Loop is a ~400-line Python system implementing a single-candidate (no populat...** · score 0.105 · [2609.05093](https://arxiv.org/abs/2609.05093)
2. **HiFi-BRep is a two-stage VAE + latent-diffusion pipeline for B-Rep generation. The topo...** · score 0.093 · [2608.16485](https://arxiv.org/abs/2608.16485)
3. **Sample-simulate-select (S3) draws N candidates per prompt from a frozen text-to-motion...** · score 0.087 · [2609.26420](https://arxiv.org/abs/2609.26420)
4. **Defines a per-edge structural invariant, edge-girth g_e (length of the shortest cycle t...** · score 0.078 · [2609.01441](https://arxiv.org/abs/2609.01441)
5. **RefineCut is a two-stage training recipe plus a closed-loop inference procedure for a c...** · score 0.077 · [2608.25622](https://arxiv.org/abs/2608.25622)
6. **A wall-first network reuses the Raster2Seq backbone (ResNet features + deformable-atten...** · score 0.075 · [2608.25608](https://arxiv.org/abs/2608.25608)
7. **SQL-Zero is a proposer-solver self-play framework in which a challenger and a solver bo...** · score 0.075 · [2609.04697](https://arxiv.org/abs/2609.04697)
8. **The paper establishes finite-sample risk bounds for mixed training (synthetic and real...** · score 0.074 · [2609.09572](https://arxiv.org/abs/2609.09572)
9. **SWYB (Stay Within Your Bounds) models the grammar as a pushdown automaton (PDA) and off...** · score 0.073 · [2608.28229](https://arxiv.org/abs/2608.28229)
10. **SRD generates N candidate trajectories, routes each to Keep/Refine/Discard via rank-nor...** · score 0.069 · [2608.24338](https://arxiv.org/abs/2608.24338)
