For each enum variant in `properties.tactic.enum` of #file:../../schemas/plan.json , please generate 3 `yaml` files in the #file:../../plans/ directory of this repo (so 36 files total). Each file should conform to #file:../../schemas/plan.json .

Notes:

- I'd like variance in the files, _e.g._:
  - Some plans should represent basic implementations, some intermediate, some advanced, etc.
  - Some plans should consist of only a few steps, some should be many, etc.
- Even though the plans should be varied so as to form a diverse dataset, each plan should be _realistic_, _i.e._ it should represent a tactical plan that could be very well be seen carried out on an actual pitch.
