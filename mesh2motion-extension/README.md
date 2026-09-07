# AutoTPose for Mesh2Motion

This Chrome/Chromium extension adds a one-click AutoTPose button to the Mesh2Motion web app at https://app.mesh2motion.org/.

It works by uploading a GLB/GLTF model to a small local Python bridge, running the Blender-based AutoTPose script, and then returning the generated T-pose output as a download.

## Files

- `manifest.json` — Chrome extension manifest.
- `content.js` — injects the AutoTPose button and uploads the model to the local bridge.
- `mesh2motion_autotpose_bridge.py` — local Python bridge that runs the Blender pipeline.

## Install

1. Open Chrome and go to `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select this folder: `mesh2motion-extension`.
5. Start the local bridge:

```bash
cd /path/to/AutoTPose
python mesh2motion-extension/mesh2motion_autotpose_bridge.py
```

6. Open https://app.mesh2motion.org/ and click the floating **AutoTPose T-pose** button.

## Requirements

- Blender installed at `/Applications/Blender.app/Contents/MacOS/Blender`
- A valid humanoid GLB/GLTF file
- The project root is the AutoTPose repo at `/path/to/AutoTPose`

## Notes

- The bridge uses the same T-pose logic already in `auto_t_pose.py`.
- It sets `--auto-rig --apply-rest-pose` to generate a rigged T-pose output through the project-local instance-rig backend.
- The result is saved as a generated `*_tpose.glb` file and downloaded back to the browser.
