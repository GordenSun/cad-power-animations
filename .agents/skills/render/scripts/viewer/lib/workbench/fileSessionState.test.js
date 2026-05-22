import assert from "node:assert/strict";
import test from "node:test";

import {
  createFileSessionSnapshot,
  FILE_SESSION_STORAGE_VERSION,
  fileSessionIndexStorageKey,
  fileSessionStorageKey,
  normalizeFileSessionState,
  pruneFileSessionState,
  readFileSessionState,
  writeFileSessionState
} from "./fileSessionState.js";
import {
  cloneThemePresetSettings,
  normalizeThemeSettings
} from "../themeSettings.js";

function createMemoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => {
      values.set(key, String(value));
    },
    removeItem: (key) => {
      values.delete(key);
    }
  };
}

function createThrowingStorage() {
  return {
    getItem: () => null,
    setItem: () => {
      throw new Error("quota exceeded");
    },
    removeItem: () => {
      throw new Error("quota exceeded");
    }
  };
}

function stepEntry(file = "parts/bracket.step", hash = "mesh-a", moduleHash = "module-a") {
  return {
    file,
    kind: "part",
    step: { hash: `step-${hash}` },
    assets: {
      glb: { hash },
      topology: { hash },
      selectorTopology: { hash },
      stepModule: { hash: moduleHash }
    }
  };
}

function dxfEntry(file = "drawings/bracket.dxf", hash = "dxf-a") {
  return {
    file,
    kind: "dxf",
    assets: {
      dxf: { hash }
    }
  };
}

function urdfEntry(file = "robots/arm.urdf", hash = "urdf-a") {
  return {
    file,
    kind: "urdf",
    assets: {
      urdf: { hash }
    }
  };
}

test("file session state stores per-file records in isolated namespaces", () => {
  const storage = createMemoryStorage();
  const entry = stepEntry();
  const blueTheme = cloneThemePresetSettings("blue");
  const darkTheme = cloneThemePresetSettings("dark");

  assert.equal(writeFileSessionState("models", entry.file, createFileSessionSnapshot({
    entry,
    slices: {
      theme: { presetId: "blue", settings: blueTheme }
    }
  }), { storage }), true);
  assert.equal(writeFileSessionState("fixtures", entry.file, createFileSessionSnapshot({
    entry,
    slices: {
      theme: { presetId: "dark", settings: darkTheme }
    }
  }), { storage }), true);

  assert.deepEqual(readFileSessionState("models", entry.file, entry, { storage }).slices.theme, {
    presetId: "blue",
    settings: blueTheme
  });
  assert.deepEqual(readFileSessionState("fixtures", entry.file, entry, { storage }).slices.theme, {
    presetId: "dark",
    settings: darkTheme
  });
});

test("file session state ignores invalid json and version mismatches", () => {
  const storage = createMemoryStorage();
  const entry = stepEntry();
  storage.setItem(fileSessionStorageKey("models", entry.file), "{not json");
  assert.equal(readFileSessionState("models", entry.file, entry, { storage }), null);

  storage.setItem(fileSessionStorageKey("models", entry.file), JSON.stringify({
    version: FILE_SESSION_STORAGE_VERSION + 1,
    fileKey: entry.file,
    slices: {
      theme: { presetId: "blue", settings: cloneThemePresetSettings("blue") }
    }
  }));
  assert.equal(readFileSessionState("models", entry.file, entry, { storage }), null);
});

test("file session state reports browser storage write failures", () => {
  const errors = [];
  const entry = stepEntry();
  const snapshot = createFileSessionSnapshot({
    entry,
    slices: {
      theme: { presetId: "blue", settings: cloneThemePresetSettings("blue") }
    }
  });

  assert.equal(writeFileSessionState("models", entry.file, snapshot, {
    storage: createThrowingStorage(),
    onWriteError: (error) => errors.push(error)
  }), false);
  assert.ok(errors.some((error) => error.key === fileSessionStorageKey("models", entry.file)));
});

test("file session state writes, reads, indexes, and prunes file records", () => {
  const storage = createMemoryStorage();
  const keptEntry = dxfEntry("drawings/kept.dxf", "dxf-kept");
  const staleEntry = dxfEntry("drawings/stale.dxf", "dxf-stale");

  writeFileSessionState("models", keptEntry.file, createFileSessionSnapshot({
    entry: keptEntry,
    slices: {
      dxf: {
        thicknessMm: 3.2,
        bendSettings: [{ id: "bend-1", direction: "down", angleDeg: 91 }]
      }
    }
  }), { storage });
  writeFileSessionState("models", staleEntry.file, createFileSessionSnapshot({
    entry: staleEntry,
    slices: {
      dxf: {
        thicknessMm: 1.5,
        bendSettings: [{ id: "bend-2", direction: "up", angleDeg: 45 }]
      }
    }
  }), { storage });

  assert.deepEqual(JSON.parse(storage.getItem(fileSessionIndexStorageKey("models"))).files, [
    keptEntry.file,
    staleEntry.file
  ]);

  assert.equal(pruneFileSessionState("models", [keptEntry.file], { storage }), true);
  assert.equal(storage.getItem(fileSessionStorageKey("models", staleEntry.file)), null);
  assert.deepEqual(JSON.parse(storage.getItem(fileSessionIndexStorageKey("models"))).files, [keptEntry.file]);
  assert.equal(readFileSessionState("models", keptEntry.file, keptEntry, { storage }).slices.dxf.thicknessMm, 3.2);
});

test("file session theme slice keeps full unsaved custom settings", () => {
  const customTheme = normalizeThemeSettings({
    ...cloneThemePresetSettings("blue"),
    background: {
      ...cloneThemePresetSettings("blue").background,
      solidColor: "#101418"
    },
    materials: {
      ...cloneThemePresetSettings("blue").materials,
      brightness: 1.19
    }
  });
  const entry = stepEntry();
  const session = normalizeFileSessionState(createFileSessionSnapshot({
    entry,
    slices: {
      theme: {
        presetId: "",
        settings: customTheme
      }
    }
  }), { fileKey: entry.file, entry });

  assert.deepEqual(session.slices.theme, {
    presetId: "",
    settings: customTheme
  });
});

test("file session state skips stale content-sensitive slices but keeps theme", () => {
  const storage = createMemoryStorage();
  const oldEntry = stepEntry("parts/bracket.step", "old-mesh", "old-module");
  const nextEntry = stepEntry("parts/bracket.step", "new-mesh", "new-module");
  const theme = cloneThemePresetSettings("blue");

  writeFileSessionState("models", oldEntry.file, createFileSessionSnapshot({
    entry: oldEntry,
    slices: {
      theme: { presetId: "blue", settings: theme },
      tab: {
        selectedPartIds: ["solid-1"],
        hiddenPartIds: ["solid-2"]
      },
      stepModule: {
        enabled: false,
        parameterValues: { width: 42 },
        animationState: { activeId: "open", elapsedSec: 1.5, speed: 1.2 }
      }
    }
  }), { storage });

  const restored = readFileSessionState("models", nextEntry.file, nextEntry, { storage });
  assert.deepEqual(restored.slices.theme, {
    presetId: "blue",
    settings: theme
  });
  assert.equal(restored.slices.tab, undefined);
  assert.equal(restored.slices.stepModule, undefined);
});

test("file session state restores urdf slices only when robot assets match", () => {
  const storage = createMemoryStorage();
  const oldEntry = urdfEntry("robots/arm.urdf", "old-urdf");
  const matchingEntry = urdfEntry("robots/arm.urdf", "old-urdf");
  const staleEntry = urdfEntry("robots/arm.urdf", "new-urdf");

  writeFileSessionState("models", oldEntry.file, createFileSessionSnapshot({
    entry: oldEntry,
    slices: {
      urdf: {
        jointValues: { shoulder: 12.5 },
        motionState: {
          activeEndEffectorName: "tool0",
          targetFrame: "base",
          targetsByEndEffector: {
            tool0: [1, 2, 3]
          },
          solvingEndEffectorName: "tool0"
        }
      }
    }
  }), { storage });

  assert.deepEqual(readFileSessionState("models", oldEntry.file, matchingEntry, { storage }).slices.urdf, {
    jointValues: { shoulder: 12.5 },
    motionState: {
      activeEndEffectorName: "tool0",
      targetFrame: "base",
      targetsByEndEffector: {
        tool0: [1, 2, 3]
      }
    }
  });
  assert.equal(readFileSessionState("models", oldEntry.file, staleEntry, { storage }).slices.urdf, undefined);
});
