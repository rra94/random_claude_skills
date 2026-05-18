# Writing area regex patterns

The classifier is keyword/regex based. Each target area in your config gets a list of
patterns; a paper matches if any pattern hits its title OR abstract (case-insensitive).

The default config (`assets/config_example.json`) ships patterns for 10 CV/robotics areas.
Add your own areas by extending `classify.target_areas` in your config.

## Principles for good patterns

1. **Use word boundaries** — `\b3d reconstruction\b`, not `3d reconstruction`. Otherwise
   "model" matches inside "modelization".
2. **Include common abbreviations** — `\bnerf\b`, `\bsfm\b`, `\bvla\b`, `\b3dgs\b`.
3. **List 5–15 alternatives per area** — being generous is fine; over-matching is recoverable
   (the user can re-classify), but missing whole sub-areas is hard to spot.
4. **Avoid matching too-generic words alone** — `\brobot\b` will match "robotic-inspired"
   etc.; pair with context (`\brobot learning\b`, `\brobot manipulation\b`).
5. **Watch case in token boundaries** — `\bsam\b` will match "Sam" anywhere, which is fine
   for "Segment Anything Model" but might catch a co-author named Sam. Test on a few papers
   if in doubt.

## Example: building a new area

To add a "Diffusion Models" area:

```json
"Diffusion Models": [
  "\\bdiffusion model(s)?\\b",
  "\\bscore[- ]based\\b",
  "\\bddpm\\b", "\\bddim\\b",
  "\\bedm\\b", "\\bflow matching\\b",
  "\\brectified flow\\b",
  "\\bconsistency model(s)?\\b",
  "\\bguided diffusion\\b"
]
```

## Common areas + suggested seed patterns

These are starting points — extend based on the conference's actual jargon (CVPR uses
slightly different terms than NeurIPS).

**LLMs**: `\bllm(s)?\b`, `\blarge language model(s)?\b`, `\binstruction[- ]tuning\b`,
`\bsft\b`, `\brlhf\b`, `\bin[- ]context learning\b`, `\bchain[- ]of[- ]thought\b`

**Multimodal**: `\bmultimodal\b`, `\bvision[- ]language\b`, `\bvlm\b`, `\bclip\b`,
`\btext[- ]to[- ]image\b`, `\bcross[- ]modal\b`

**RL**: `\breinforcement learning\b`, `\bpolicy gradient\b`, `\bppo\b`, `\bdpo\b`,
`\bq[- ]learning\b`, `\bactor[- ]critic\b`, `\boffline rl\b`

**Generative Models**: `\bgenerative model(s)?\b`, `\bgan(s)?\b`, `\bdiffusion model(s)?\b`,
`\bvae(s)?\b`, `\bautoregressive (image|video) generation\b`

**3D**: see `3D Reconstruction` in default config (NeRF, GS, SfM, MVS, etc.)

**Robotics**: `\brobot(ic|ics) learning\b`, `\bmanipulation\b`, `\bimitation learning\b`,
`\bdiffusion policy\b`, `\bvla\b`, `\bteleoperation\b`, `\bdexterous\b`

## When to switch to LLM classification

The regex approach struggles with:
- Long-tail topic phrasings ("novel view synthesis" → not matched by `\b3d reconstruction\b`)
- Sub-fields requiring contextual judgment ("we propose a method for X" where X is the area
  but is only mentioned in one sentence buried in the abstract)
- New buzzwords that emerge between conferences

If your shortlist quality is poor (lots of off-topic papers, or you can find papers in your
target area that the classifier missed), see `llm_classifier.md` for swapping in Claude.
