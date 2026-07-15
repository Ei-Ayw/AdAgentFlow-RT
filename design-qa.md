# Design QA

- source visual truth paths:
  - `/var/folders/x8/25tcwf7s4k36cvx22p8vw9sh0000gn/T/codex-clipboard-ZntaCz.png`
  - `/var/folders/x8/25tcwf7s4k36cvx22p8vw9sh0000gn/T/codex-clipboard-XN67lQ.png`
- generated architecture asset: `/Users/apple/AdAgentFlow/app/web/assets/studio/backend-system-map.png`
- implementation URL: `http://127.0.0.1:8000/web/#/`
- intended viewport: desktop, approximately 2048 × 1060 CSS px
- state: homepage reliability architecture section, default node `事务级可靠投递`
- implementation screenshot path: unavailable after the latest changes

## Evidence

- The source image was opened at original resolution and used as the spatial-language reference: five isometric platforms, looping paths, and external callouts.
- A project-specific raster illustration was generated with five black isometric infrastructure platforms connected by white data paths. It contains no baked-in labels or placeholders.
- HTML callouts map the five platforms to real repository capabilities: persistent task intake, transactional outbox, idempotent Agent workers, LLM-as-Judge quality gate, and Repair/DLQ recovery.
- Callouts are interactive and update a technical readout with stack, trace, and telemetry details.
- Four restrained data pulses continuously circulate around the infrastructure loop; the map breathes subtly and readout changes animate in. Motion is disabled by the existing reduced-motion rule.
- The large rounded outer borders, radii, and shadows were removed from the homepage hero, pipeline, reliability map, and recent-creations section while internal structure was preserved.
- The Vite production build completed successfully and all 18 frontend tests passed.
- Full-view comparison: blocked because the browser runtime exposes no controllable browser instance for a post-change capture.
- Focused-region comparison: blocked for callout placement, image crop, and readout rhythm for the same reason.
- Primary interaction intended for browser testing: observing the circulation loop, selecting each of the five architecture callouts, verifying animated readout transitions, and navigating to the operations console.
- Console errors checked: blocked because no controllable browser instance was available.

## Findings

- [P2] Latest rendered architecture section has not been visually captured.
  - Location: homepage reliability architecture section.
  - Evidence: the reference and generated asset are available, but no post-change browser screenshot can be captured.
  - Impact: exact overlay placement, wrapping, responsive layout, and runtime console state cannot be certified.
  - Fix: refresh the local page in a controllable browser, capture the same viewport, and compare the architecture section with the source reference.

## Required fidelity surfaces

- Typography: HTML labels use the existing product type scale; rendered wrapping remains unverified.
- Spacing/layout: five callouts are positioned around the five generated platforms; exact browser placement remains unverified.
- Colors/tokens: black, graphite, white, and cool gray match the existing product palette and adapt the light-blue source reference intentionally.
- Image quality: the generated 1672 × 941 PNG is a real raster asset with crisp isometric forms; browser scaling remains unverified.
- Copy/content: every visible technical claim is grounded in repository implementation.

## Comparison history

- Iteration 1: replaced the list-style backend section with a generated isometric system map and interactive project-specific callouts. Automated build and template checks passed; post-fix browser evidence remains unavailable.

## Implementation checklist

- [x] Generate and save a real isometric architecture raster asset.
- [x] Adapt the reference composition to the product's black-and-white visual system.
- [x] Map all five visual nodes to real backend capabilities.
- [x] Add interactive callouts and technical readout.
- [x] Add restrained circulating data flow, node feedback, and reduced-motion behavior.
- [x] Add responsive behavior for narrow screens.
- [x] Remove the annotated capsule-style outer section frames.
- [x] Pass production build and frontend tests.
- [ ] Capture and compare the post-change desktop rendering.

final result: blocked
