/**
 * Custom Blockly block definitions for Tiago robot control.
 * Each block maps directly to an action in the backend executor.
 */

Blockly.defineBlocksWithJsonArray([
  {
    type: "move_forward",
    message0: "Move Forward  speed %1 m/s  for %2 s",
    args0: [
      { type: "field_number", name: "SPEED",    value: 0.3, min: 0.05, max: 0.5,  precision: 0.05 },
      { type: "field_number", name: "DURATION", value: 2,   min: 0.5,  max: 30,   precision: 0.5  }
    ],
    previousStatement: null,
    nextStatement: null,
    colour: 160,
    tooltip: "Move the robot forward at the given speed for the given duration."
  },
  {
    type: "move_backward",
    message0: "Move Backward  speed %1 m/s  for %2 s",
    args0: [
      { type: "field_number", name: "SPEED",    value: 0.3, min: 0.05, max: 0.5,  precision: 0.05 },
      { type: "field_number", name: "DURATION", value: 2,   min: 0.5,  max: 30,   precision: 0.5  }
    ],
    previousStatement: null,
    nextStatement: null,
    colour: 230,
    tooltip: "Move the robot backward at the given speed for the given duration."
  },
  {
    type: "turn_left",
    message0: "Turn Left  speed %1 rad/s  for %2 s",
    args0: [
      { type: "field_number", name: "SPEED",    value: 0.5, min: 0.1, max: 1.0, precision: 0.1 },
      { type: "field_number", name: "DURATION", value: 2,   min: 0.5, max: 30,  precision: 0.5 }
    ],
    previousStatement: null,
    nextStatement: null,
    colour: 65,
    tooltip: "Turn the robot left (counter-clockwise)."
  },
  {
    type: "turn_right",
    message0: "Turn Right  speed %1 rad/s  for %2 s",
    args0: [
      { type: "field_number", name: "SPEED",    value: 0.5, min: 0.1, max: 1.0, precision: 0.1 },
      { type: "field_number", name: "DURATION", value: 2,   min: 0.5, max: 30,  precision: 0.5 }
    ],
    previousStatement: null,
    nextStatement: null,
    colour: 65,
    tooltip: "Turn the robot right (clockwise)."
  },
  {
    type: "stop",
    message0: "Stop",
    previousStatement: null,
    nextStatement: null,
    colour: 0,
    tooltip: "Stop all robot motion immediately."
  },
  {
    type: "wait",
    message0: "Wait %1 s",
    args0: [
      { type: "field_number", name: "DURATION", value: 1, min: 0.5, max: 30, precision: 0.5 }
    ],
    previousStatement: null,
    nextStatement: null,
    colour: 290,
    tooltip: "Pause execution for the given duration."
  },

  // ── Sensor blocks ──────────────────────────────────────────────────────────

  {
    type: "lidar_compare",
    message0: "obstacle %1 %2 m",
    args0: [
      {
        type: "field_dropdown",
        name: "OP",
        options: [
          ["closer than", "<"],
          ["farther than", ">"]
        ]
      },
      {
        type: "field_number",
        name: "VALUE",
        value: 1.0,
        min: 0.1,
        max: 5.0,
        precision: 0.1
      }
    ],
    output: "Boolean",
    colour: 20,
    tooltip: "True if the nearest obstacle is closer or farther than the given distance."
  },

  // ── Control blocks ─────────────────────────────────────────────────────────

  {
    type: "if_else",
    message0: "if %1",
    args0: [{ type: "input_value", name: "CONDITION", check: "Boolean" }],
    message1: "do %1",
    args1: [{ type: "input_statement", name: "THEN" }],
    message2: "else %1",
    args2: [{ type: "input_statement", name: "ELSE" }],
    previousStatement: null,
    nextStatement: null,
    colour: 210,
    tooltip: "Execute 'do' blocks if condition is true, otherwise execute 'else' blocks."
  }
]);


/**
 * Extract the lidar_compare condition from a block's CONDITION input.
 */
function getCondition(block) {
  const condBlock = block.getInputTargetBlock("CONDITION");
  if (!condBlock) return null;
  return {
    op:    condBlock.getFieldValue("OP"),
    value: parseFloat(condBlock.getFieldValue("VALUE"))
  };
}

/**
 * Serialize all blocks connected to a named statement input.
 */
function getStatementBlocks(parentBlock, inputName) {
  const commands = [];
  let block = parentBlock.getInputTargetBlock(inputName);
  while (block) {
    commands.push(blockToCommand(block));
    block = block.getNextBlock();
  }
  return commands;
}

/**
 * Recursively serialize a single block into a command object.
 */
function blockToCommand(block) {
  const action = block.type;
  const params = {};

  if (action === "if_else") {
    return {
      action: "if_else",
      condition: getCondition(block),
      then: getStatementBlocks(block, "THEN"),
      else: getStatementBlocks(block, "ELSE")
    };
  }

  if (block.getField("SPEED"))    params.speed    = parseFloat(block.getFieldValue("SPEED"));
  if (block.getField("DURATION")) params.duration = parseFloat(block.getFieldValue("DURATION"));
  return { action, params };
}

/**
 * Convert the top-level block chain in the workspace to a JSON command list.
 * Returns an array of {action, params, ...} objects (may be nested).
 */
function workspaceToCommands(workspace) {
  const topBlocks = workspace.getTopBlocks(true);
  if (!topBlocks.length) return [];

  const commands = [];
  let block = topBlocks[0];
  while (block) {
    commands.push(blockToCommand(block));
    block = block.getNextBlock();
  }
  return commands;
}
