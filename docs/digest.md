# hexgen digest — 2026-11-12

**13** new backlog item(s) in the last 7 day(s).

## New this window

- **Simple-PAT: zeroth-order optimization over a procedural generator's control parameters...** · score 0.051
  - _Contributions:_ Introduces procedural adversarial learning (PAL), a minimax training and adversarial evaluation framework that searches a procedural generator's parameter space for hard instances. Presents Simple-PAT and PAL-Dojo, generators for normals, segmentation and pose. Reports reduced worst-case error versus standard and robust-training baselines.
  - _Applicable to our work:_ Analogous to our inverse factory: instead of sampling random valid programs uniformly, adaptively search the factory's parameter space for program/B-rep instances where the current decoder (or verifier-screened best-of-N) fails and oversample them. Also gives a worst-case evaluation protocol for the synthetic-to-real domain gap.
  - _Additional context:_ Vision tasks only; zeroth-order search fits a non-differentiable mesher pipeline. Risk: adversarial samples may be unrealistic CAD; needs a validity filter.
  - _Impact_ 0.50 · _Applicability_ 0.72 · _Confidence_ 0.71 · _Effort_ 5.0/10
  [2611.06890](https://arxiv.org/abs/2611.06890)
- **Trains LLMs to write CadQuery programs with GRPO using a deterministic CAD-CAE verifier...** · score 0.043
  - _Contributions:_ PhyCAD is a physics-aware Text-to-CAD framework that trains language models to produce executable CadQuery programs under geometric and physical constraints. It contributes a dataset linking parametric CAD with geometric specs, loading conditions and limits, an automated CAD-CAE verifier, and a Hierarchical Balanced Advantage for GRPO that keeps cross-level priority while giving fine-grained within-level feedback.
  - _Applicable to our work:_ Directly transferable: our frozen verifier (compiles, zero inverted elements, Jacobian/aspect bounds, boundary fidelity) is naturally a level hierarchy. The hierarchical advantage (between-level + within-level peer ranking) could drive GRPO/RL fine-tuning of the hexgen decoder or weight rejection-sampled SFT, avoiding flat-reward masking of validity failures.
  - _Additional context:_ Targets LLM-written CadQuery, not a small graph-transformer with pointer heads; RL on a 27M model needs adapting. Verifier-in-loop idea maps closely to our item 1 and 6. Code released.
  - _Impact_ 0.50 · _Applicability_ 0.66 · _Confidence_ 0.66 · _Effort_ 5.0/10
  [2611.09401](https://arxiv.org/abs/2611.09401)
- **Given a failed proof and verifier error, TopoVerus (QwQ-32B based) generates a structur...** · score 0.037
  - _Contributions:_ TopoVerus internalizes counterexample-guided diagnosis: counterexample generation is trained not as a standalone task but via downstream credit, being rewarded when conditioning on it yields a safe, verifier-passing proof. A dependency-aware curriculum with a topological graph reward encourages repairing prerequisite invariants first. Across 471 Verus problems it beats Claude Sonnet 4.5, and its counterexamples also boost other repair tools.
  - _Applicable to our work:_ Directly maps to hexgen's repair/edit distillation care-area: train a repair head that, given a broken hexproj program and the frozen verifier's failure report (e.g. which faces/blocks produced inverted elements or failed surface match), first emits a localized diagnosis then an edited program, with credit assigned only through downstream verifier pass (diagnosis rewarded by usefulness, not standalone correctness). The dependency-ordered curriculum is analogous to fixing upstream block/sweep commands before dependent projections. The safety gate idea maps to forbidding edits that change the target B-rep.
  - _Additional context:_ Uses a 32B LM with RL; hexgen is a 27M model, so take the training recipe (diagnose-then-repair with downstream-credited intermediate, ordering curriculum) rather than the scale. Our verifier already gives richer-than-binary signals (Jacobian, fidelity), which could serve as the 'counterexample' analog cheaply. Code and weights are released.
  - _Impact_ 0.50 · _Applicability_ 0.60 · _Confidence_ 0.74 · _Effort_ 6.0/10
  [2611.13627](https://arxiv.org/abs/2611.13627)
- **Controlled comparison of a self-improving embodied coding agent with and without Criter...** · score 0.028
  - _Contributions:_ The paper defines Criteria Exposure in self-improving embodied agents and shows that the success-rate advantage under original criteria vanishes when judged by slightly changed, instruction-faithful criteria. Skills learned under exposure transfer poorly across tasks. It proposes instruction-faithful criteria that better reflect the quality of agent-generated programs.
  - _Applicable to our work:_ Cautionary evidence for the frozen-verifier flywheel: when a generator is trained/selected against a verifier it can overfit the verifier's quirks. Suggests auditing hexgen's verifier thresholds for hidden rules and validating best-of-N self-improvement with held-out/perturbed criteria.
  - _Additional context:_ Embodied robotics setting; relevance is by analogy to verifier-in-the-loop training only. No code released that we saw beyond a project page.
  - _Impact_ 0.30 · _Applicability_ 0.42 · _Confidence_ 0.45 · _Effort_ 2.0/10
  [2611.08318](https://arxiv.org/abs/2611.08318)
- **Analysis and online replay experiments of allocation policies (round-robin, Thompson Sa...** · score 0.024
  - _Contributions:_ Shows difficulty-proportional ('harder gets more') allocation captures little oracle gain on hard workloads, and that with a verifier the prior quality matters more than the policy. Provides a decision guide on when adaptive allocation helps.
  - _Applicable to our work:_ Informs how to spend a fixed best-of-N budget across B-rep inputs: use a cheap prior (face count, past pass rates) with Thompson sampling and avoid wasting samples on hopeless parts. Reinforces that the frozen verifier must have rare false accepts.
  - _Additional context:_ Text/math/code workloads; relevant only to inference-budget policy, not modeling.
  - _Impact_ 0.25 · _Applicability_ 0.54 · _Confidence_ 0.35 · _Effort_ 2.0/10
  [2611.06372](https://arxiv.org/abs/2611.06372)
- **VGSC proposes candidate next steps from the base LM and accepts/resamples using step-le...** · score 0.023
  - _Contributions:_ Proposes Verifier-Guided Self-Consistency, a stochastic decoding framework combining step-level verification and future-outcome estimates. Interprets it as approximate sampling from a verifier-tilted trajectory distribution. Shows higher average accuracy than baselines across benchmarks, generators and verifiers.
  - _Applicable to our work:_ Prefix-level accept/resample guided by a step verifier plus a value estimate maps to guiding hexgen decoding over program prefixes with a learned prefix-validity/compile-success predictor, tilting sampling toward executable programs before best-of-N screening by the frozen verifier.
  - _Additional context:_ Evaluated on text reasoning, not programs; our verifier scores only complete programs, so the prefix value model must be trained from rollouts (Monte Carlo continuation labels are cheap here).
  - _Impact_ 0.50 · _Applicability_ 0.66 · _Confidence_ 0.42 · _Effort_ 6.0/10
  [2611.06606](https://arxiv.org/abs/2611.06606)
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
- **Restrict global attention to a randomized near-neighbor graph built once by within-bin...** · score 0.009
  - _Contributions:_ NearFormer is a graph transformer whose global attention is restricted to a randomized near-neighbor graph, giving attention support of linear size O(|E|+nk). It adds geometry-aware long-range channels with few edges and is analysed in terms of rewiring and over-squashing.
  - _Applicable to our work:_ Hybrid of global attention and local message passing with geometry-derived attention bias is relevant to the graph-transformer B-rep encoder (e.g. biasing attention by face adjacency/geometric proximity), though sparsity is unnecessary at 7-15 faces.
  - _Additional context:_ Scalability benefit is moot at our graph size; the geometric-bias idea is the only transferable part.
  - _Impact_ 0.15 · _Applicability_ 0.48 · _Confidence_ 0.37 · _Effort_ 3.0/10
  [2611.12186](https://arxiv.org/abs/2611.12186)
- **Turn-level best-of-N with a generator-selector framework: a generator proposes candidat...** · score 0.008
  - _Contributions:_ Evaluates turn-level best-of-N sampling with an LLM selector comparing candidate actions directly. Shows accuracy and consistency gains on terminal tasks and analyzes behavior shifts.
  - _Applicable to our work:_ Command-level candidate selection during program decoding: sample several next DSL commands and pick with a learned critic rather than only whole-program best-of-N.
  - _Additional context:_ Selector is an LLM judging text actions; for us a trained critic or partial-execution check would replace it.
  - _Impact_ 0.30 · _Applicability_ 0.48 · _Confidence_ 0.28 · _Effort_ 5.0/10
  [2611.06868](https://arxiv.org/abs/2611.06868)
- **We compare six execution-free predictors from four families on Qwen3-Coder-30B and gpt-...** · score 0.008
  - _Contributions:_ The paper compares six execution-free correctness predictors (output confidence, EigenScore consistency, hidden-state probes, causal-subspace probes) for LLM code judgments under benchmark and language shift. It adapts two causal localization methods to code and finds they improve robustness to language shift for verdict correctness on Qwen3-Coder, but not consistently elsewhere. For program correctness, predictors mostly identify hard problems and rank candidates within a problem poorly.
  - _Applicable to our work:_ Learned critic/value signals for ranking best-of-N candidates when the frozen verifier is expensive; shows such predictors triage problems better than they rank candidates, and degrade under shift, relevant to synthetic-to-real CAD gap.
  - _Additional context:_ LLM code-judging setting, not geometric programs; transfer is indirect. Weak within-problem ranking limits use for best-of-N selection.
  - _Impact_ 0.25 · _Applicability_ 0.36 · _Confidence_ 0.43 · _Effort_ 5.0/10
  [2611.07876](https://arxiv.org/abs/2611.07876)
- **Objective programmatic verifiers flag guideline violations and serve as rewards for RLV...** · score 0.004
  - _Contributions:_ Describes a deployed pipeline generating animated icons, focusing on image generation. Designs objective verifiers and uses them for RLVR, raising pass rate from 15.7% to 58.7%.
  - _Applicable to our work:_ Supports our verifier-in-the-loop line: a frozen machine-checkable verifier as RL reward when no supervised data exists; dual use as reward and deployment gate mirrors our best-of-N screening.
  - _Additional context:_ Image domain; evidence of the pattern rather than a transferable mechanism. Reward hacking risk; they use an independent judge.
  - _Impact_ 0.20 · _Applicability_ 0.42 · _Confidence_ 0.37 · _Effort_ 7.0/10
  [2611.06123](https://arxiv.org/abs/2611.06123)

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
