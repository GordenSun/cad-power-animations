# CAD Explorer MoveIt2 Server

The local `moveit2_server` powers CAD Explorer's optional SRDF IK and path-planning controls. Start it only when reviewing an SRDF in CAD Explorer and the user needs pose solving or planning. It reads the selected SRDF, linked URDF, and request settings. It is not a replacement for a full MoveIt configuration package.

## Setup and runtime

```bash
scripts/moveit2_server/setup.sh
scripts/moveit2_server/check-moveit2-server.sh
scripts/moveit2_server/run-moveit2-server.sh
```

Run these commands from the `render` skill directory. The server defaults to:

```text
127.0.0.1:8765
```

Use the configured ROS 2 / MoveIt2 environment. Do not install ROS 2 or MoveIt2 packages into the repository CAD `.venv`.

CAD Explorer connects to `ws://127.0.0.1:8765/ws` in local dev unless `EXPLORER_MOVEIT2_WS_URL` or the browser `?moveit2Ws=` query override is set.

## Request protocol

Requests use `protocolVersion: 1`.

Supported request types:

- `srdf.solvePose`
- `srdf.planToPose`

Use native joint-value fields:

- `startJointValuesByName`
- `jointValuesByName`
- trajectory `positions`

Legacy `startJointValuesByNameDeg`, `jointValuesByNameDeg`, and `positionsDeg` are compatibility aliases. Input `*Deg` fields convert degrees to native radians for angular joints; output `*Deg` fields convert native radians back to degrees. Prismatic joints remain linear distances.

## Pose targets

Pose targets require:

- `target.frame`;
- `target.xyz`;
- `target.endEffector`;
- `target.targetLink` or `moveit2.targetLink` when the desired TCP is not obvious.

`moveit2.targetFrame` is validated during context construction, but the current adapter still reads the pose frame from `target.frame`.

Orientation can be provided as exactly one of:

```json
"quat_xyzw": [0, 0, 0, 1]
```

or:

```json
"rpy": [0, 0, 0]
```

If no orientation is provided, `moveit2.ik.positionOnly` defaults to true. If `positionOnly` is false, an orientation must be supplied.

## Example solve request

```json
{
  "id": "solve-1",
  "protocolVersion": 1,
  "type": "srdf.solvePose",
  "payload": {
    "file": "robot.srdf",
    "target": {
      "endEffector": "tool_eef",
      "targetLink": "tool0",
      "frame": "base_link",
      "xyz": [0.4, 0.0, 0.2],
      "quat_xyzw": [0, 0, 0, 1]
    },
    "moveit2": {
      "planningGroup": "manipulator",
      "ik": {
        "positionOnly": false,
        "timeout": 0.05,
        "attempts": 1,
        "tolerance": 0.002
      }
    },
    "startJointValuesByName": {
      "shoulder_pan_joint": 0.0
    }
  }
}
```

## Limitations

- The server uses generated config dictionaries and defaults such as KDL and OMPL; those defaults are not universal.
- Success depends on the linked URDF, SRDF, collision geometry, solver availability, and MoveIt environment.
- It is appropriate for smoke tests and local checks, not for certifying a production planning configuration.
- Cache invalidation is based on linked URDF/SRDF file size and modification time.

## Smoke-test report

Report:

```text
MoveIt2 server:
- environment check: passed
- IK solve: passed for manipulator/tool0
- plan-to-pose: failed, planner timeout at 1.0 s
- positionOnly: false
- target frame: base_link
- target link: tool0
```
