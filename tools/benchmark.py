# MASTER IMPLEMENTATION PROMPT — MFruit Galaxy for MFruitOS
## Production-Quality Ambient Space Visualisation Application

**Project:** MFruit Galaxy  
**Application ID:** `mfruit-galaxy`  
**Operating system:** MFruitOS  
**Source repository:** https://github.com/Mengkungkao/MFruitOS  
**Target environment:** Linux desktop with a graphical session  
**Primary display:** One HDMI-connected monitor or television  
**Primary objective:** Create a complete, independently installable MFruitOS application that displays high-quality animated galaxies, night skies, nebulae, auroras, planets and other ambient visual effects.

---

# 1. Your role and mission

Act as a senior Linux application developer, graphics programmer, embedded systems engineer, software architect, and test engineer.

Your task is to develop **MFruit Galaxy**, a fully functional visualisation application for the existing MFruitOS project.

The application must transform a Linux desktop's HDMI-connected monitor or television into a cinematic ambient display. It should be capable of running indefinitely, displaying visually appealing scenes without requiring an internet connection.

The initial target is one HDMI display connected to a Linux desktop with a working graphical environment. The architecture should allow future support for other Linux devices, Raspberry Pi systems, multiple displays, and the existing Whisplay Display HAT when technically supported.

This is an application-development task, not a request to create a mock-up, produce a design document, or build an unrelated standalone program.

You must inspect the actual repository, implement working software, run the available tests, document any limitations, and provide clear instructions for launching and installing the application.

**Do not stop after inspecting the repository or producing a plan. Complete the implementation to the extent supported by the available environment and clearly identify anything that requires physical hardware verification.**

# 2. Source-code requirements

Use the existing MFruitOS repository as the source of truth.

Repository:
https://github.com/Mengkungkao/MFruitOS

If a local repository or uploaded ZIP is available in the development environment, inspect and work on that copy first. Do not silently replace the working source with a different revision.

Before making changes:

1. Inspect the complete repository structure.
2. Read `AGENTS.md` and all applicable development instructions.
3. Read `README.md` and the current application development documentation.
4. Inspect the application templates and existing application manifests.
5. Inspect the SDK, application lifecycle, host APIs, display interfaces, launcher, daemon and application manager.
6. Inspect the updater, packaging mechanism, test scripts and release conventions.
7. Examine any existing MFruit Galaxy prototype, including its renderer, launch scripts, diagnostics and unit tests.
8. Inspect Git status, the current branch and existing uncommitted changes when Git metadata is available.
9. Identify supported Python versions, operating-system versions and existing dependencies.
10. Run relevant baseline tests before modifying the source.

Use the latest source actually available to you. Do not assume that a previously described file path or architectural detail is correct until the source confirms it.

Produce a concise technical audit identifying the existing application contract, the current display architecture, available host APIs, existing test coverage and the smallest safe integration path.

Do not overwrite user modifications, delete unrelated files, reset the repository, or perform a destructive cleanup.

# 3. Core architectural requirement: integrate with MFruitOS

MFruit Galaxy must be a genuine MFruitOS application.

It must not become an unrelated desktop application that bypasses the MFruitOS launcher, application manager, installation conventions and lifecycle.

Use the current repository's documented application structure, SDK and manifest format.

Integrate with the existing mechanisms for:

- Application discovery.
- Application installation and removal.
- Application launching and shutdown.
- Input handling.
- Logging and error reporting.
- Application configuration and writable data.
- Application versioning.
- Dependency checks.
- Application updates and rollback.
- Packaging and release distribution.

Follow the actual repository contract rather than inventing APIs, manifest fields, function names or installation commands.

The app must appear in the existing MFruitOS launcher when installed through the supported mechanism. Launching it must start the galaxy visualisation, and closing it must return control to MFruitOS according to the existing lifecycle rules.

Do not create a replacement application manager, duplicate launcher, competing daemon or independent update system.

## Existing Whisplay compatibility

The existing Whisplay Display HAT integration must continue to function.

The current architecture is documented as using `whisplay-daemon` and a shared framebuffer for the HAT. Confirm this against the actual repository before implementation.

Do not assume that this framebuffer represents an HDMI display.

Do not redirect the Whisplay framebuffer, change its resolution, modify its hardware driver or take ownership of its display merely to make the HDMI application work.

If the existing MFruitOS SDK only supports Whisplay rendering, implement the smallest maintainable extension needed to support a desktop graphical display.

Any new host or rendering backend must be isolated from the existing backend. Existing applications must retain their current behaviour unless an essential, documented compatibility change is justified.

# 4. Establish a working HDMI rendering path first

This is the highest-priority technical milestone.

Before developing the complete animation engine, prove that MFruit Galaxy can create a real window in the user's Linux graphical session and render animated content to the intended HDMI monitor.

Do not assume HDMI output works simply because a window can be created, a framebuffer can be written, or a test image can be generated.

## 4.1 Detect the graphical environment

Implement a diagnostic command or script that reports the available graphics environment.

Inspect, where applicable:

- Linux distribution and version.
- CPU architecture.
- Python or other relevant runtime version.
- Presence of X11 or Wayland.
- Whether the application can access the graphical session.
- Relevant display environment variables.
- Available monitors and resolutions using the display system's supported tools.
- Availability of the proposed rendering library.
- GPU and graphics-driver information when obtainable without elevated privileges.
- Availability of relevant OpenGL or OpenGL ES capabilities.
- Whether the system is operating headlessly.
- Missing dependencies and actionable remedies.

Treat environment variables as clues, not proof that a graphical display is accessible.

Do not require root privileges for normal application operation.

If the monitor or graphical session cannot be detected, report the actual failure rather than pretending the display is available.

## 4.2 Select the rendering backend

Inspect the existing application SDK and the actual host environment before choosing a backend.

Consider an existing supported graphical API or a lightweight solution such as SDL2, Pygame, pyglet, Tkinter or another suitable native Linux graphics mechanism.

Do not combine multiple rendering frameworks without a clear technical reason.

The selected backend must support the actual required features:

- Full-screen rendering.
- Window resizing and resolution changes.
- Keyboard events.
- Frame timing.
- Animation.
- Clean resource release.
- Useful error reporting.
- Appropriate rendering performance on the target hardware.
- Compatibility with the existing MFruitOS application lifecycle.

For a desktop graphical session, prefer a window-based renderer that uses the desktop's existing display system. Do not introduce direct framebuffer access or DRM/KMS ownership unless the verified platform requires it and the integration has been designed explicitly.

If hardware acceleration is available and useful, support it. If only software rendering is available, provide a functional fallback.

Do not make GPU support mandatory without evidence that the target system requires it.

## 4.3 Implement the minimum viable rendering test

Create an initial application or internal diagnostic mode that displays:

1. A black or deep-space background.
2. A field of stars.
3. Subtle, continuous star movement or twinkling.
4. One moving meteor or another obvious animation.
5. Basic frame-rate and rendering diagnostics when requested.

The test must actually animate. A static screenshot does not establish that rendering is working.

Test both normal windowed operation and full-screen operation.

Where monitor enumeration is supported, display the detected output names and resolutions.

When there is one HDMI monitor, the application should be able to show the scene full-screen on that monitor without unnecessary desktop decorations.

If several displays exist on the host, allow the user to select an output when the backend supports reliable display selection.

If multiple-display targeting is not supported by the selected environment, report the limitation.

Do not change the global primary display or forcibly reconfigure the desktop merely to launch the application.

## 4.4 HDMI verification status

Clearly distinguish between:

- Unit tests.
- Automated graphical tests.
- Virtual display tests.
- Rendering-library capability tests.
- Successful window creation on a live graphical session.
- Actual physical HDMI output verified on hardware.

Do not state that physical HDMI has been tested unless it has.

If you cannot access physical HDMI hardware, still implement the rendering path and automated tests, then provide precise hardware validation instructions.

# 5. User experience and application modes

Build a polished, cinematic ambient application rather than a conventional settings-heavy dashboard.

The app must support two main modes.

## 5.1 Ambient viewing mode

This is the primary mode.

Requirements:

- Fill the selected display when full-screen mode is active.
- Hide the application interface and mouse cursor where the environment permits.
- Render the selected scene without persistent UI overlays.
- Keep animation continuous and visually smooth.
- Avoid unwanted flashing, black frames and visible transition jumps.
- Handle window focus changes appropriately.
- Pause or reduce rendering when background execution is unnecessary.
- Allow the user to exit or open the settings panel without losing control of the system.
- Remain stable during long-running operation.

Use a high-quality dark colour palette with deep blacks, navy blue, violet, cyan, restrained magenta and other appropriate space-inspired colours.

Do not make the entire display constantly bright. Include dark, relaxing modes suitable for evening viewing.

## 5.2 Control panel

Implement an attractive and accessible settings interface consistent with MFruitOS.

Provide controls for:

- Selecting a scene.
- Starting, pausing and resuming animation.
- Animation speed.
- Brightness or visual intensity.
- Star density.
- Nebula intensity.
- Meteor frequency.
- Scene-transition duration.
- Automatic scene rotation.
- Scene-rotation interval.
- Visual quality preset.
- Full-screen mode.
- Display selection when supported.
- Sleep timer.
- Resetting settings to defaults.

Controls must change the actual rendering behaviour. No decorative or nonfunctional buttons are permitted.

Settings should be available without depending on a touchscreen.

Use keyboard navigation and the existing MFruitOS input mechanisms where applicable.

Avoid intrusive notifications, unnecessary menus, and permanent statistics over the ambient scene.

# 6. Scene engine

Implement a modular scene system.

Each scene should expose a consistent lifecycle appropriate to the existing application framework. A scene should be initialised, updated, rendered, paused or resumed, and cleaned up without leaving resources behind.

Separate scene logic from the display backend. A scene must not need to know whether the host uses an accelerated renderer, a software renderer or another supported display path.

Implement these scenes.

## Scene A — Deep-space galaxy

Create a cinematic spiral galaxy featuring:

- A luminous central core.
- Multiple spiral arms.
- Dense star clusters.
- Dark dust lanes.
- Layered starfields.
- Subtle depth and parallax.
- Slow rotation.
- Atmospheric glow.
- Gradual changes in colour intensity.

Movement must remain subtle enough for ambient viewing.

Do not simulate a physically accurate astronomical model unless the implementation actually uses appropriate scientific calculations.

## Scene B — Night sky

Create a natural-looking night sky featuring:

- Numerous stars of different apparent brightness.
- Independently varying twinkle rates.
- Subtle background gradients.
- Optional cloud layers.
- Occasional meteors.
- A minimal dark mode.
- Optional horizon silhouettes.

Ensure that star twinkling appears varied rather than synchronised.

## Scene C — Nebula

Create layered gas-cloud effects using appropriate gradients, particles, textures or shaders.

Support slow transitions between blue, cyan, violet, pink and red.

Avoid excessively bright flashes and abrupt colour changes.

The effect should feel organic and dimensional rather than like random coloured noise.

## Scene D — Aurora

Implement flowing aurora bands with:

- Smooth, wave-like movement.
- Gradual changes in opacity.
- Green and cyan as the primary colours.
- Optional blue and violet accents.
- A dark sky background.
- Optional distant mountain silhouettes.

Avoid repeating, mechanical-looking waves.

## Scene E — Solar system

Create an ambient solar-system visualisation with the Sun and recognisable planets.

Include optional orbital paths, simple planetary motion and subtle illumination.

Provide an optional information overlay identifying planets.

Clearly distinguish illustrative motion from real astronomical positions.

Never label invented or arbitrary planetary positions as scientifically accurate.

## Scene F — Meteor shower

Implement multiple meteor trails with:

- Randomised but controlled spawn timing.
- Variable direction and speed.
- Bright heads and fading trails.
- Smooth opacity decay.
- Configurable frequency.
- Limits on simultaneous trails.

Avoid continuous bursts of bright flashes.

## Scene G — Minimal ambient mode

Create a restrained night scene featuring:

- A nearly black background.
- Sparse stars.
- Very slow movement.
- Low brightness.
- No persistent UI.
- Minimal rendering workload.

This must remain usable for long periods and when the display is in a dark room.

## Scene architecture

The scene system must permit future scenes to be added without rewriting the launcher, display host or existing scenes.

Use shared utilities for particles, colour transitions, star generation, animation timing and resource management wherever suitable.

Do not duplicate large amounts of rendering code across all scenes.

# 7. Procedural graphics, assets and visual quality

Prioritise original procedural graphics.

Use mathematical models, particle systems, gradients, cached textures and shaders where appropriate.

Third-party assets may be used only when their licences permit the intended distribution. Record their provenance and licence requirements.

Do not download visual assets every time the application launches.

The core scenes must work offline.

Avoid enormous pre-rendered videos as the default rendering mechanism. Pre-rendered assets may be optional if justified by measured performance and documented storage requirements.

## Visual quality criteria

- Smooth and believable animation.
- Distinct visual identities between scenes.
- Consistent lighting and colour transitions.
- No obvious repeated particle patterns.
- No excessive aliasing.
- No unnecessary UI elements.
- No abrupt frame-to-frame colour changes.
- No large amounts of visual clutter.
- No visual effects that substantially degrade performance without user consent.

Static and slowly changing elements should be cached when practical.

# 8. Rendering and performance

The initial target is a Linux desktop with a single HDMI monitor, potentially running at 1280 × 720 or 1920 × 1080.

Design the rendering system to scale down to less powerful Linux devices where practical, but do not compromise the primary desktop experience unnecessarily.

Implement configurable quality presets:

**Eco**
- Low particle count.
- Limited background effects.
- Minimal CPU and GPU usage.
- Reduced frame rate if necessary.

**Balanced**
- Recommended defaults.
- Attractive visual quality.
- Controlled particle counts.
- Stable frame pacing.

**High**
- Increased particle density.
- More detailed galaxy and nebula effects.
- Additional depth and lighting effects where supported.

**Ultra**
- Optional enhanced rendering for capable hardware.
- More complex shaders and particle systems.
- Never select automatically unless capability checks justify it.

Requirements:

1. Use a consistent animation time source.
2. Use delta-time-based motion rather than frame-count-based motion.
3. Prevent animation speed from changing substantially with different frame rates.
4. Use frame pacing or an equivalent mechanism to prevent uncontrolled busy loops.
5. Reuse objects and buffers where appropriate.
6. Avoid per-pixel Python loops across the entire display.
7. Avoid repeated large allocations during normal frames.
8. Limit particle counts and shader complexity.
9. Cache static background elements where practical.
10. Avoid rendering when suspended or paused.
11. Avoid unnecessary full-screen redraws in software-rendering paths.
12. Handle window resizing without rebuilding the entire scene unnecessarily.
13. Release graphics resources when the application exits.
14. Profile before making performance claims.
15. Report measured results and the hardware used.

Do not promise a fixed frame rate until the implementation has been measured on the target device.

# 9. Resolution, scaling and display management

The first release targets one HDMI monitor.

Nevertheless, design a display interface that can support additional display configurations in the future.

The display layer should provide, when supported:

- Connected display enumeration.
- Display-name identification.
- Current resolution.
- Current refresh rate.
- Full-screen presentation.
- Window-resize events.
- Display disconnection handling.
- Recovery after display reconnection.
- Appropriate aspect-ratio handling.
- Renderer recreation when necessary.
- Clean display resource release.

Do not stretch circles into ellipses or distort galaxy structures when the display aspect ratio changes.

Use resolution-independent scene coordinates or an equivalent approach.

If the user changes display resolution, adapt the rendering automatically whenever the graphical backend supports this.

Do not forcibly change system display settings without an explicit user action.

## Future multiple-display support

Prepare the interface for future use on:

- A single HDMI monitor.
- Multiple HDMI monitors.
- Different scenes on different monitors.
- Mirrored ambient scenes.
- Devices with HDMI and other supported display outputs.

Do not falsely claim that independent rendering across multiple physical outputs is supported unless it has been implemented and tested.

For the initial release, prioritise one reliably working HDMI display.

# 10. Input handling

Use the existing MFruitOS input APIs wherever possible.

The desktop backend should support keyboard input through the selected graphical framework.

Recommended bindings:

| Key | Action |
|---|---|
| Left arrow | Previous scene |
| Right arrow | Next scene |
| Space | Pause or resume animation |
| Enter | Confirm the selected action |
| F11 | Toggle fullscreen |
| Tab | Move between controls |
| B | Toggle the control panel when not editing a text field |
| Esc | Close the panel or request application exit according to the app lifecycle |
| Q | Request application exit |

Ensure that every exit path uses the documented MFruitOS shutdown mechanism.

Do not terminate the entire MFruitOS host or launcher process when the app closes.

Handle window-close events and system shutdown requests correctly.

Avoid intercepting operating-system shortcuts unnecessarily.

Do not introduce new Whisplay button gestures that conflict with the current SDK.

# 11. Application configuration and persistence

Persist user preferences through the existing MFruitOS application-data conventions.

Store appropriate settings, including:

- Last selected scene.
- Visual quality preset.
- Animation speed.
- Brightness.
- Particle density.
- Meteor frequency.
- Scene-transition duration.
- Automatic scene rotation.
- Scene-rotation interval.
- Fullscreen preference.
- Preferred output when reliably supported.
- Sleep-timer configuration.
- Optional visual effects.

Configuration files must be validated before use.

Handle:

- Missing configuration files.
- Invalid JSON or equivalent configuration formats.
- Invalid values.
- Missing optional settings.
- Unsupported future settings.
- Partial writes.
- Permission errors.

Use safe, atomic persistence where appropriate.

When configuration loading fails, fall back to sensible defaults and report the issue without crashing.

Never write application preferences into unrelated MFruitOS system configuration files.

Provide a restore-defaults operation.

Document the configuration location and schema.

# 12. Sleep, pause and unattended operation

This app is intended to run as an ambient display for extended periods.

Implement a configurable sleep timer.

Support pausing the animation and optionally reducing rendering workload when the application loses focus.

Where practical, allow the user to configure the display behaviour when the timer expires:

- Pause the scene.
- Switch to minimal ambient mode.
- Return to MFruitOS.
- Close the application through the supported lifecycle.

Do not disable operating-system power management globally.

Do not prevent the host from shutting down or restarting normally.

Do not change system brightness or power settings without an explicit user action and confirmed backend support.

Provide predictable behaviour for application suspension and resumption.

# 13. Astronomical information and offline operation

Core animation must not depend on internet access.

Optional features may include:

- Local date and time.
- Constellation overlays.
- Planet identification.
- Real astronomical night-sky rendering.
- Location-specific sky configuration.
- Optional information overlays.

Scientific functionality must use a recognised astronomical calculation library or documented astronomical algorithms when accuracy matters.

Do not pretend a random starfield is a real-time astronomical simulation.

Do not invent the user's geographic location, current planetary positions, sunrise time, celestial events or astronomical observations.

Location and network-dependent features must remain optional.

The application must start and operate normally when the computer is offline.

# 14. Error handling and reliability

The application must never leave MFruitOS unusable after an error.

Handle the following conditions:

- Display unavailable.
- Graphical session unavailable.
- Missing rendering dependencies.
- Renderer initialisation failure.
- Graphics-driver failure.
- Window creation failure.
- Invalid display mode.
- Unsupported resolution.
- Display disconnection.
- Failed configuration writes.
- Unexpected scene errors.
- Application shutdown during rendering.
- User interruption.
- Repeated failed launches.

Provide actionable error messages.

For example, distinguish between a missing Python package and the absence of a graphical session.

Avoid indefinite retry loops.

Do not start duplicate animation workers or background tasks when returning to the application.

Ensure that the renderer, event loop, timers, threads, windows and resources are cleaned up correctly.

Never silently fall back to rendering on the wrong output when the user has explicitly selected a supported display.

Do not create persistent services or startup entries without a clear requirement and explicit design approval.

# 15. Security and maintainability

- Do not require root for normal operation.
- Do not write directly to protected system directories outside the documented installation procedure.
- Do not execute downloaded code as an ordinary asset.
- Do not introduce an unnecessary embedded web server.
- Do not store credentials or secrets.
- Validate imported configuration.
- Use safe file paths.
- Avoid shell commands assembled from untrusted user input.
- Record third-party asset licences.
- Follow the repository's dependency and packaging conventions.
- Document any required system packages.
- Keep the application modular.
- Add type annotations where compatible with the existing project.
- Follow the repository's formatting and lint rules.
- Avoid unnecessary abstractions and excessive dependencies.

# 16. Recommended source organisation

Follow the actual MFruitOS conventions rather than imposing a new project layout.

The conceptual components should be separated into:

**Application entry point**
- Starts the application.
- Reads configuration.
- Connects to the MFruitOS lifecycle.
- Creates and cleans up application resources.

**Display host**
- Opens the desktop rendering surface.
- Reports available capabilities.
- Manages resolution and window events.
- Owns only the display resources assigned to the application.

**Renderer**
- Draws scenes.
- Manages animation time and rendering quality.
- Handles scene transitions.
- Releases graphics resources.

**Scene manager**
- Registers available scenes.
- Changes scenes.
- Pauses and resumes scene updates.
- Manages transitions.

**Scene modules**
- Galaxy.
- Night sky.
- Nebula.
- Aurora.
- Solar system.
- Meteor shower.
- Minimal ambient scene.

**Controls**
- Settings panel.
- Keyboard handling.
- Scene selection.
- Fullscreen handling.

**Configuration**
- Loads defaults.
- Validates settings.
- Saves preferences.
- Supports restoration to defaults.

**Diagnostics**
- Reports graphics environment.
- Reports rendering-backend availability.
- Reports connected displays when supported.
- Records useful error information.

**Tests**
- Unit tests.
- Lifecycle tests.
- Rendering tests.
- Packaging tests.
- Environment-dependent integration tests.

These are architectural responsibilities, not mandatory file names. Use existing MFruitOS patterns wherever available.

# 17. Automated testing

Write tests for the actual implementation.

## Unit tests

Test:

- Configuration defaults.
- Configuration validation.
- Invalid configuration recovery.
- Scene registration.
- Scene selection.
- Scene switching.
- Animation pause and resume.
- Delta-time behaviour.
- Automatic scene rotation.
- Quality-profile selection.
- Meteor frequency limits.
- Resource cleanup.
- Event handling.
- Timer behaviour.

Keep tests deterministic where possible.

Use seeded randomness for tests involving procedurally generated scenes.

## Display and rendering tests

Test:

- Rendering into an offscreen surface when supported.
- Correct surface initialisation.
- Scene rendering at multiple resolutions.
- Window resize handling.
- Aspect-ratio calculations.
- Renderer failure recovery.
- Fullscreen state changes.
- Correct shutdown after rendering errors.
- Display capability reporting.

A screenshot test may help validate composition but cannot demonstrate continuous animation by itself.

## MFruitOS integration tests

Test:

- Manifest validation.
- Application discovery.
- Installation.
- Application launch.
- Normal exit.
- Force-stop behaviour.
- Return to the launcher.
- Settings persistence across relaunch.
- Resource cleanup.
- Update compatibility.
- Application removal.
- Whisplay application regression tests.

Follow the repository's real lifecycle and app-management contract.

## Environment-specific tests

Test X11 or Wayland paths only where the relevant backend and environment are available.

If a test requires a real graphical session, label it accordingly.

Where useful, use a virtual display for automated rendering tests, but do not present a virtual display result as physical HDMI verification.

## Performance tests

Measure:

- Application startup time.
- Frames per second.
- Frame-time distribution.
- CPU utilisation.
- Memory consumption.
- Resource growth over time.
- Scene-transition behaviour.
- Rendering performance at 720p and 1080p.
- Idle workload when paused.
- Behaviour during extended operation.

Record the operating system, graphics backend, CPU, GPU where relevant, and display resolution used for the results.

Do not invent measurements.

# 18. Installation and release integration

Package the application according to the repository's existing application conventions.

The app must be independently installable and removable.

Use the supported MFruitOS mechanisms and the existing application template where appropriate.

Suggested application metadata, subject to the actual schema:

- Name: MFruit Galaxy
- ID: `mfruit-galaxy`
- Category: Visuals / Ambient
- Description: Animated galaxies, night skies and ambient space scenes for connected displays.
- Primary target: Linux desktop graphical display.
- Internet required for core functionality: No.

Provide:

- Valid manifest.
- Correct application entry point.
- Launch script with proper permissions.
- Required assets.
- Dependency documentation.
- Test scripts.
- Useful application icon.
- Version metadata.
- Installation instructions.
- Uninstallation instructions.
- Update and rollback compatibility.
- Release packaging suitable for the existing updater.

Do not invent unsupported manifest fields.

Do not publish the application or modify the remote GitHub repository without authorisation.

Prepare a release-ready package, and document the exact process required to publish it through the current MFruitOS distribution mechanism.

# 19. Documentation

Update the relevant application documentation.

Document:

1. What MFruit Galaxy does.
2. Supported operating environments.
3. Known graphical-backend requirements.
4. Required dependencies.
5. Installation steps.
6. Launch instructions.
7. Keyboard controls.
8. Fullscreen behaviour.
9. Settings and configuration storage.
10. Graphics diagnostics.
11. Troubleshooting missing display access.
12. Common X11 and Wayland issues.
13. Test commands.
14. How to add a new scene.
15. How to add or improve a display backend.
16. Application removal.
17. Current limitations.
18. Actual verification status.

Include commands that match the real repository.

Never invent installation paths or claim that an unverified command works.

# 20. Implementation workflow

Complete the work in the following order.

## Phase 1 — Repository audit

Inspect the current source and report:

- Existing application contract.
- Available SDK APIs.
- Current display architecture.
- Existing desktop support, if any.
- Current prototype components.
- Dependencies.
- Relevant tests.
- Required minimal changes.

Preserve the user's existing work.

## Phase 2 — Display architecture

Select a rendering backend based on the actual target environment.

Define the minimum host interface necessary for rendering, input, resizing, lifecycle events and cleanup.

Keep the existing Whisplay backend intact.

Do not introduce unnecessary changes to the operating system.

## Phase 3 — Minimal animated starfield

Implement and run the simplest functional rendering application.

Display a moving starfield and an occasional meteor.

Support windowed mode, fullscreen mode, keyboard controls and clean shutdown.

Implement diagnostics for display discovery and renderer initialisation.

Do not start building every scene before this milestone works.

## Phase 4 — MFruitOS integration

Package the application using the real manifest and application lifecycle.

Confirm that it can be discovered and launched through the supported manager.

Ensure that shutdown returns control normally.

Test that existing MFruitOS applications remain unaffected.

## Phase 5 — Core scene engine

Implement galaxy, night sky, nebula, aurora, solar system, meteor shower and minimal ambient scenes.

Add shared scene utilities, procedural graphics and quality settings.

Ensure that every scene can be selected, paused, resumed and stopped cleanly.

## Phase 6 — Interface and configuration

Implement the control panel, saved settings, scene transitions, automatic scene rotation and sleep timer.

Ensure that each control works and that configuration errors do not crash the app.

## Phase 7 — Performance and reliability

Profile the renderer and address measured bottlenecks.

Test long-running animation, resource release, resizing, application focus changes and failure recovery.

Avoid adding expensive effects without measuring their impact.

## Phase 8 — Automated regression testing

Run the repository's documented test suite.

Run the new app tests and all relevant regression checks.

Inspect the diff for unrelated modifications.

Check shell syntax, manifest validity, packaging, resource paths and dependency requirements.

Correct discovered failures.

## Phase 9 — Verification and delivery

Provide a final report stating:

- What was implemented.
- What files were created or changed.
- Which rendering backend was selected and why.
- How the app is integrated with MFruitOS.
- Which automated tests passed.
- Which tests failed or could not run.
- Which operating systems and display backends were tested.
- Whether physical HDMI output was actually verified.
- Any known limitations.
- Exact installation and launch commands.
- Remaining steps for the user.

Do not conceal incomplete work.

# 21. Strict completion requirements

The application is not complete merely because the program starts or displays a static image.

A successful initial implementation must:

1. Run on the target Linux desktop graphical session.
2. Render a continuously animated starfield.
3. Support full-screen viewing on the HDMI-connected monitor.
4. Handle resizing and animation timing appropriately.
5. Respond correctly to keyboard input.
6. Close cleanly.
7. Avoid requiring root privileges for normal rendering.
8. Provide actionable diagnostics when the graphical environment is unavailable.
9. Preserve existing MFruitOS and Whisplay functionality.
10. Include automated tests and installation instructions.

The full application must additionally implement functional scenes, settings, transitions, configuration persistence, resource cleanup, and packaging.

Physical hardware verification must be identified separately from automated testing.

# 22. Non-negotiable rules

- Inspect the real source before modifying it.
- Follow the existing application contract.
- Preserve all unrelated user modifications.
- Do not replace or redesign MFruitOS for this application.
- Do not confuse the Whisplay HAT framebuffer with HDMI output.
- Do not invent APIs, manifest fields, test results or hardware capabilities.
- Do not introduce unnecessary dependencies.
- Do not require root for ordinary application operation.
- Do not leave placeholder scenes or nonfunctional controls.
- Do not change system display settings without explicit user action.
- Do not create competing launchers or background daemons.
- Do not claim physical HDMI, GPU acceleration, multi-monitor support or performance results without evidence.
- Do not stop after creating a technical plan.
- Do not publish changes to GitHub without authorisation.
- Keep the implementation modular, testable, maintainable and independently updatable.

# Final instruction

Begin by inspecting the current MFruitOS repository, its application template, the existing desktop prototype if available, and the actual display-host architecture.

Identify the smallest safe implementation that can render a continuously animated starfield through the Linux graphical session on the HDMI-connected monitor.

Implement that path first, then integrate the app into MFruitOS and build the remaining scenes and controls.

Finish the implementation, run the available tests, correct the issues you find, and provide an honest verification report. If physical HDMI hardware is unavailable, deliver the working code and precise hardware-testing instructions without claiming that physical output has been verified.

**The final result must be a real MFruitOS application, not just a standalone demo, a mock-up, or a written proposal.**#!/usr/bin/env python3
"""Measure frame cost per scene, resolution and quality, without showing anything.

    python3 tools/benchmark.py                              # 1280x720 and 1920x1080, balanced and high
    python3 tools/benchmark.py --sizes 1920x1080 --qualities eco --seconds 6 --json out.json

Each scene runs unpaced in a hidden window (the frame is rendered into an
offscreen target the size of the screen and presented); every 30th frame the
pixels are read back, which waits for the GPU, so GPU work is included in the
averages. Reported per run: frames per second without a cap, frame time
(median, 95th percentile), CPU time per frame and the process's peak memory.

This measures rendering cost on *this* machine. It is not the frame rate on a
visible screen (vsync, compositor and scan-out are not included); use
``run.sh --stats`` on the real screen for that.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def measure(display, scene_id, size, quality_name, seconds, settings_cls, seed=7):
    from app.engine import Engine
    from app.scenes.base import SceneContext, resolve_quality
    canvas = display.canvas
    settings = settings_cls()
    settings.set("transition_seconds", 0)
    quality = resolve_quality(quality_name, display.accelerated)
    canvas.width, canvas.height = size
    target = canvas.target(*size, name="bench")
    engine = Engine(canvas, settings, lambda: SceneContext(size[0], size[1], quality, settings,
                                                           seed=seed,
                                                           accelerated=display.accelerated,
                                                           max_texture=canvas.max_texture),
                    synchronous=True)
    started = time.perf_counter()
    engine.request(scene_id, "benchmark")
    with canvas.into(target):
        engine.draw()
    prepare = time.perf_counter() - started
    engine.fade_start -= 60
    frames, times = 0, []
    cpu0 = time.process_time()
    wall0 = last = time.perf_counter()
    while time.perf_counter() - wall0 < seconds:
        engine.update(1 / 60)
        with canvas.into(target):
            engine.draw(0.85)
            if frames % 30 == 29:
                canvas.read_rgba()                 # wait for the GPU
        canvas.image(target, 0, 0, size[0], size[1])
        canvas.present()
        now = time.perf_counter()
        times.append(now - last)
        last = now
        frames += 1
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    engine.close()
    target.destroy()
    times.sort()
    return {
        "scene": scene_id, "size": f"{size[0]}x{size[1]}", "quality": quality.name,
        "prepare_s": round(prepare, 2), "frames": frames,
        "uncapped_fps": round(frames / wall, 1),
        "frame_ms_p50": round(1000 * times[len(times) // 2], 2),
        "frame_ms_p95": round(1000 * times[int(len(times) * 0.95)], 2),
        "cpu_ms_per_frame": round(1000 * cpu / max(1, frames), 2),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenes", default="all")
    parser.add_argument("--sizes", default="1280x720,1920x1080")
    parser.add_argument("--qualities", default="balanced,high")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--renderer", default="auto")
    parser.add_argument("--video-driver", default="")
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)
    from app.config import Settings
    from app.display import session as sessions
    from app.display.desktop import DesktopDisplay
    from app.scenes import catalog
    if args.video_driver:
        os.environ["SDL_VIDEODRIVER"] = args.video_driver
    else:
        found = sessions.find_session()
        if found.chosen is None:
            raise SystemExit(f"benchmark: {found.problem}")
        sessions.apply(found.chosen)
    sizes = [tuple(int(v) for v in s.split("x")) for s in args.sizes.split(",")]
    biggest = max(sizes)
    display = DesktopDisplay(fullscreen=False, window_size=biggest, renderer=args.renderer,
                             hidden=True).open()
    scenes = catalog.SCENE_IDS if args.scenes == "all" else args.scenes.split(",")
    results = []
    try:
        print(f"# {platform.node()} {platform.machine()} {display.driver} "
              f"({'GPU' if display.accelerated else 'software'}) on {display.video_driver}")
        print(f"{'scene':10} {'size':10} {'quality':9} {'prep s':>6} {'fps':>7} {'p50 ms':>7} "
              f"{'p95 ms':>7} {'cpu ms':>7} {'rss MB':>7}")
        for size in sizes:
            for quality in args.qualities.split(","):
                for scene_id in scenes:
                    r = measure(display, scene_id, size, quality, args.seconds, Settings)
                    results.append(r)
                    print(f"{r['scene']:10} {r['size']:10} {r['quality']:9} {r['prepare_s']:6.2f} "
                          f"{r['uncapped_fps']:7.1f} {r['frame_ms_p50']:7.2f} {r['frame_ms_p95']:7.2f} "
                          f"{r['cpu_ms_per_frame']:7.2f} {r['peak_rss_mb']:7.1f}", flush=True)
    finally:
        display.close()
    if args.json:
        with open(args.json, "w") as handle:
            json.dump({"machine": platform.machine(), "node": platform.node(),
                       "renderer": display.driver, "results": results}, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
