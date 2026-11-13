# hexgen digest — 2026-11-13

**9** new backlog item(s) in the last 7 day(s).

## New this window

- **Trains LLMs to write CadQuery programs with GRPO using a deterministic CAD-CAE verifier...** · score 0.043
  - _Contributions:_ PhyCAD is a physics-aware Text-to-CAD framework that trains language models to produce executable CadQuery programs under geometric and physical constraints. It contributes a dataset linking parametric CAD with geometric specs, loading conditions and limits, an automated CAD-CAE verifier, and a Hierarchical Balanced Advantage for GRPO that keeps cross-level priority while giving fine-grained within-level feedback.
  - _Applicable to our work:_ Directly transferable: our frozen verifier (compiles, zero inverted elements, Jacobian/aspect bounds, boundary fidelity) is naturally a level hierarchy. The hierarchical advantage (between-level + within-level peer ranking) could drive GRPO/RL fine-tuning of the hexgen decoder or weight rejection-sampled SFT, avoiding flat-reward masking of validity failures.
  - _Additional context:_ Targets LLM-written CadQuery, not a small graph-transformer with pointer heads; RL on a 27M model needs adapting. Verifier-in-loop idea maps closely to our item 1 and 6. Code released.
  - _Impact_ 0.50 · _Applicability_ 0.66 · _Confidence_ 0.66 · _Effort_ 5.0/10
  [2611.09401](https://arxiv.org/abs/2611.09401)
- **Negative-Only Policy Optimization (NOPO) treats verified positives as unlabeled and upd...** · score 0.039
  - _Contributions:_ The paper formalizes one-sided verifiability (OSV), where verified negatives are reliable counterexamples but verified positives are merely non-falsified. It proposes NOPO, which learns only from suppressing verified negatives relative to a reference policy, with a group-level adapter. It reports pass@k gains over baselines on code, logic and math with unit-test, constraint-check and LLM self-verifiers when oracle rewards are unavailable.
  - _Applicable to our work:_ Directly maps onto hexgen's frozen verifier: compile/zero-inverted-element/Jacobian failures are trustworthy negatives, while 'passes' may still be poor programs (e.g. templates that game boundary-fidelity thresholds). NOPO-style negative-only fine-tuning on best-of-N rollouts could raise structural validity (care-area 1) and serve as a safer alternative to rejection-sampled SFT in the verifier-in-the-loop flywheel (care-area 6), especially pass@k which matches best-of-N deployment.
  - _Additional context:_ Only the abstract was available; loss details, hyperparameters and model scales are not verified here. Evaluated on LLM reasoning tasks, not small graph-conditioned decoders; transfer to a 27M model with pointer heads is plausible but untested. Note hexgen's verifier is fairly strict, so positives are less noisy than in the OSV setting — benefit may be largest for the softer checks.
  - _Impact_ 0.55 · _Applicability_ 0.72 · _Confidence_ 0.39 · _Effort_ 4.0/10
  [2611.17287](https://arxiv.org/abs/2611.17287)
- **Given a failed proof and verifier error, TopoVerus (QwQ-32B based) generates a structur...** · score 0.037
  - _Contributions:_ TopoVerus internalizes counterexample-guided diagnosis: counterexample generation is trained not as a standalone task but via downstream credit, being rewarded when conditioning on it yields a safe, verifier-passing proof. A dependency-aware curriculum with a topological graph reward encourages repairing prerequisite invariants first. Across 471 Verus problems it beats Claude Sonnet 4.5, and its counterexamples also boost other repair tools.
  - _Applicable to our work:_ Directly maps to hexgen's repair/edit distillation care-area: train a repair head that, given a broken hexproj program and the frozen verifier's failure report (e.g. which faces/blocks produced inverted elements or failed surface match), first emits a localized diagnosis then an edited program, with credit assigned only through downstream verifier pass (diagnosis rewarded by usefulness, not standalone correctness). The dependency-ordered curriculum is analogous to fixing upstream block/sweep commands before dependent projections. The safety gate idea maps to forbidding edits that change the target B-rep.
  - _Additional context:_ Uses a 32B LM with RL; hexgen is a 27M model, so take the training recipe (diagnose-then-repair with downstream-credited intermediate, ordering curriculum) rather than the scale. Our verifier already gives richer-than-binary signals (Jacobian, fidelity), which could serve as the 'counterexample' analog cheaply. Code and weights are released.
  - _Impact_ 0.50 · _Applicability_ 0.60 · _Confidence_ 0.74 · _Effort_ 6.0/10
  [2611.13627](https://arxiv.org/abs/2611.13627)
- **A set-conditioned SE(3) flow-matching model (DiT) is pretrained on procedurally generat...** · score 0.021
  - _Contributions:_ BrickFlow is the first method to reconstruct a LEGO object from an image and its partset. It pretrains a set-conditioned SE(3) flow prior on procedural assemblies, adapts it to images with ~1% of the data, and introduces a training-free connectivity-field guidance energy that raises assembly validity for every model size and halves disconnected components in large assemblies.
  - _Applicable to our work:_ Three transferable ideas: (1) procedural/synthetic pretraining then small-data finetuning on real data, with an ablation showing the synthetic prior is what gives structural validity (19.4% vs 2.3%) — analogous to hexgen's inverse-factory data and the synthetic-to-real CAD gap (care-area 2); (2) a differentiable/analytic constraint energy applied as test-time guidance to push samples toward validity without retraining — an analogue for verifier-guided decoding of hexgen programs, e.g. a soft validity critic steering beam/best-of-N (care-area 1); (3) best-of-N validity curves vs part count and symmetry-aware matching of interchangeable parts, related to pointer ambiguity over congruent faces (care-area 4).
  - _Additional context:_ Continuous flow model over poses, not an autoregressive program decoder, so guidance does not transfer directly to discrete token decoding; the mechanism would need reformulating as a value/critic over prefixes. Absolute validity is still low (~35%). Code and data released.
  - _Impact_ 0.40 · _Applicability_ 0.48 · _Confidence_ 0.66 · _Effort_ 6.0/10
  [2611.17321](https://arxiv.org/abs/2611.17321)
- **A hierarchical graph abstraction and coarse-to-fine generation pipeline separating coar...** · score 0.017
  - _Contributions:_ The paper introduces a hierarchical serialization pipeline for autoregressive graph generation and studies community coarsening, hierarchical tokenization and order randomization. Traversal-based hierarchy improves distributional and structural fidelity, and gains depend on how well the hierarchy aligns with the target distribution.
  - _Applicable to our work:_ Hierarchical, order-randomized tokenization of structured objects is analogous to serializing hexgen programs (e.g. block then sweep/projection hierarchy) and to ordering augmentation for the decoder.
  - _Additional context:_ Molecule-focused; transfer is at the level of serialization/ordering design.
  - _Impact_ 0.30 · _Applicability_ 0.48 · _Confidence_ 0.60 · _Effort_ 5.0/10
  [2611.12160](https://arxiv.org/abs/2611.12160)
- **FairlySymbolic evolves a triplet of parser (grid -> typed multigraph of core-knowledge...** · score 0.016
  - _Contributions:_ The paper presents FairlySymbolic, a fully symbolic evolutionary program-synthesis system for ARC that co-evolves the input parser, the transformation program and the output projector, effectively evolving a task-specific DSL. Parser symbols are grounded in core-knowledge theory, and an object-aware fitness grades partially correct outputs beyond pixel matching. It was the only evolutionary entry scored on the ARC-AGI-2 semi-private set.
  - _Applicable to our work:_ Two transferable ideas: (1) a graded, structure-aware partial-credit score for imperfect programs (object/structure-level rather than exact match) could become a dense value/critic signal for hexgen's verifier-guided best-of-N or prefix search, instead of only binary pass/fail; (2) their proposed future 'learned fitness estimator' predicting mutation distance to a correct program, trained on progressively mutated correct programs, maps directly onto inverse-factory data: mutate valid hexproj programs to train a repair-distance critic.
  - _Additional context:_ Purely symbolic EA, no learning; the mechanism worth borrowing is the fitness design and mutation-distance idea, not the system. ARC grids are far from B-rep geometry. The ablation is the most useful evidence that graded fitness beats coarse pass/fail for search.
  - _Impact_ 0.30 · _Applicability_ 0.42 · _Confidence_ 0.52 · _Effort_ 4.0/10
  [2611.13831](https://arxiv.org/abs/2611.13831)
- **Training-free, verifier-guided agentic framework separating visual planning (DrawingInt...** · score 0.013
  - _Contributions:_ AMSchem is a training-free agentic framework that generates human-readable schematics from analog netlists. It splits planning from executable geometry and applies bounded repair patches that are revalidated by deterministic validators. The authors also introduce AMSchem-Bench with 64 circuits of 12 types.
  - _Applicable to our work:_ Pattern of a frozen deterministic validator gating generation plus bounded local repair of failed outputs; could inspire a repair loop for hexgen programs that fail compile/inverted-element checks, and a two-stage plan-then-executable-IR split.
  - _Additional context:_ Different domain (circuits, LLM prompting, no training); only the verifier/repair methodology transfers.
  - _Impact_ 0.25 · _Applicability_ 0.42 · _Confidence_ 0.61 · _Effort_ 5.0/10
  [2611.12333](https://arxiv.org/abs/2611.12333)
- **ISLA (Invariant Slice Attention) is a slice-attention transformer where no learned oper...** · score 0.010
  - _Contributions:_ The paper introduces ISLA, claimed as the first slice-attention surrogate exactly equivariant to the Euclidean group, invariant to units and consistent under mesh refinement. It proves these invariances and shows measure-weighted slice attention is a ratio of quadratures. Empirically it has the lowest errors on AeroZoo, is second to GLOBE on AirfRANS, and its error changes by at most 1.1% under changes of presentation.
  - _Applicable to our work:_ The hexgen encoder-level rotation-invariance line is closed, but two ISLA ideas are new relative to it: (1) a boundary-derived length unit and measure-weighted (area-weighted) aggregation over boundary faces, giving invariance to tessellation/resampling and scale — relevant to the coordinate/tokenization domain gap between factory-synthesized and real CAD B-reps (care-area 2); (2) its finding that principal-axis canonical frames at inference still leave 5-6x errors while full SO(3) augmentation nearly closes the gap, informative for deployment-time canonical-frame vs augmentation choices (care-area 5). Anchor-relative distance/angle features could also augment face tokens in the graph transformer.
  - _Additional context:_ PDE surrogate, not a generative/program model; outputs are fields, not discrete pointer decisions. hexgen B-reps have only ~7-15 faces, so quadrature/remeshing consistency matters less than for dense meshes. Exact equivariance conflicts with hexgen's need to emit absolute coordinates in a closed vocabulary — would require canonicalizing outputs. Code promised in NVIDIA PhysicsNeMo.
  - _Impact_ 0.25 · _Applicability_ 0.36 · _Confidence_ 0.66 · _Effort_ 6.0/10
  [2611.17141](https://arxiv.org/abs/2611.17141)
- **Restrict global attention to a randomized near-neighbor graph built once by within-bin...** · score 0.009
  - _Contributions:_ NearFormer is a graph transformer whose global attention is restricted to a randomized near-neighbor graph, giving attention support of linear size O(|E|+nk). It adds geometry-aware long-range channels with few edges and is analysed in terms of rewiring and over-squashing.
  - _Applicable to our work:_ Hybrid of global attention and local message passing with geometry-derived attention bias is relevant to the graph-transformer B-rep encoder (e.g. biasing attention by face adjacency/geometric proximity), though sparsity is unnecessary at 7-15 faces.
  - _Additional context:_ Scalability benefit is moot at our graph size; the geometric-bias idea is the only transferable part.
  - _Impact_ 0.15 · _Applicability_ 0.48 · _Confidence_ 0.37 · _Effort_ 3.0/10
  [2611.12186](https://arxiv.org/abs/2611.12186)

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
