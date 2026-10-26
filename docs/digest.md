# hexgen digest — 2026-10-26

**4** new backlog item(s) in the last 7 day(s).

## New this window

- **Compiles schemas into context-parameterized transition programs: cold compilation speci...** · score 0.028
  - _Contributions:_ Presents DConstrain, an exact grammar-constrained decoder for diffusion LMs that supports arbitrary property order without enumerating field subsets. Token-effect grouping provably preserves the Viterbi optimum and token-labeled path distribution. On BFCL it compiles all schemas and cuts end-to-end latency while keeping 100% schema validity.
  - _Applicable to our work:_ Grammar/schema-constrained decoding is directly relevant to making hexproj programs compile: the symbolic transition-program idea could encode the DSL grammar plus context guards (e.g. which face indices/blocks are in scope) as a decoding mask for the pointer heads. The compile-ahead-of-forward-pass overlap is also reusable for best-of-N sampling. Our decoder is autoregressive, so the parallel-token compatibility machinery is mostly unneeded.
  - _Additional context:_ Targets JSON-schema tool calling in diffusion LMs, not geometry; transfer is the constrained-decoding mechanism only. Pointer-head masking would need custom state tracking.
  - _Impact_ 0.50 · _Applicability_ 0.60 · _Confidence_ 0.46 · _Effort_ 5.0/10
  [2610.30920](https://arxiv.org/abs/2610.30920)
- **Maps each graph to a sequence of WL colors, encodes it with a VAE into a Gaussian laten...** · score 0.014
  - _Contributions:_ WL-SeqVAE is a sequence-based VAE for graph generation that uses Weisfeiler-Leman node colors as discrete structural tokens. Graph generation becomes sequence generation, with compatibility constraints derived from the colors guiding decoding. It is competitive with established baselines on several local structural and molecular metrics.
  - _Applicable to our work:_ Constraint-guided autoregressive decoding of graph-structured outputs is analogous to masking invalid face/edge pointers during program decoding; WL colors could also serve as symmetry-aware node tokens/positional features for the B-rep face graph (congruent-face ambiguity).
  - _Additional context:_ Molecular/generic graphs only; no program or CAD setting. Competitive rather than SOTA. Constraints are structural compatibility, not execution validity.
  - _Impact_ 0.25 · _Applicability_ 0.42 · _Confidence_ 0.67 · _Effort_ 5.0/10
  [2610.32650](https://arxiv.org/abs/2610.32650)
- **Represents a B-rep as an Edge-Adjacency Graph (EAG) and applies hybrid discrete/continu...** · score 0.011
  - _Contributions:_ Introduces the Edge-Adjacency Graph as a graph representation of B-reps for generation, and GraphCAD, a hybrid graph diffusion model with geometry-aware denoising. Also builds EAGBench, a large dataset of engineering CAD parts aggregated from existing repositories. Claims state-of-the-art geometric fidelity and distributional alignment against sequence-based baselines, including models with more than 50 faces.
  - _Applicable to our work:_ The EAG representation and edge-level graph encoding are a candidate alternative or complement to the face-adjacency graph in the hexgen encoder; the render-to-point-set geometric grounding of node attributes and the EAGBench B-rep corpus are possible sources for real-CAD diversity (domain gap). The diffusion decoder itself is not a program generator.
  - _Additional context:_ Generates B-rep graphs, not programs, so no direct structural-validity mechanism; the SE(3) equivariance aspect touches our closed rotation line. Code availability not confirmed in the extracted text.
  - _Impact_ 0.30 · _Applicability_ 0.48 · _Confidence_ 0.46 · _Effort_ 6.0/10
  [2610.30974](https://arxiv.org/abs/2610.30974)
- **A single policy acts as Questioner and Solver over executable environments whose progra...** · score 0.011
  - _Contributions:_ Tempo-Zero closes a loop of executable environments, execution-verified self-play, and environment evolution for video reasoning. Executing a program renders a video with exact ground-truth options and intervals, replacing consensus-based pseudo-labels. Solver performance steers a curriculum and the policy selects rule changes that enrich later event dynamics.
  - _Applicable to our work:_ The loop of program execution giving exact verifiable rewards, plus a curriculum that evolves the generator's program distribution from learner performance, maps to hexgen's inverse factory and frozen verifier: adaptively re-weight factory sampling toward program types the decoder fails, and filter synthetic pairs by execution-consistency checks.
  - _Additional context:_ Video-VLM domain; transfer is conceptual (verifier-in-the-loop, adaptive synthetic curriculum), not directly a mesh/CAD method. Code only promised ('will be made publicly available'). RL-based, heavier than hexgen's SFT flywheel.
  - _Impact_ 0.30 · _Applicability_ 0.42 · _Confidence_ 0.42 · _Effort_ 5.0/10
  [2610.32433](https://arxiv.org/abs/2610.32433)

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
