"""Context provider: structured Factorio primitive catalog."""

from yoitsu_contracts.bundle import context_provider


@context_provider(name="script_docs")
def provide_script_docs(goal: str) -> str:
    """Return the supported factorio_script primitive catalog."""
    return """\
# Factorio Script Primitive Catalog

Use `factorio_script(name="<primitive>", args={...})` for all Factorio reads,
writes, and waits. Do not call raw RCON, `/c` Lua, `require("scripts...")`, or
shell commands.

## Read primitives

- `system.capabilities`: list available primitive names.
- `read.tick`: return the current game tick.
- `read.world_summary`: run the bundle world summary script.
- `read.game_state`: query entity/resource/force state. Use `args={"query": "summary"}` unless a narrower query is needed.
- `read.production`: query production state. Use `args={"query": "summary"}` unless a narrower query is needed.
- `read.logistics`: query logistics state. Use `args={"query": "summary"}` unless a narrower query is needed.
- `read.research`: query current research status.
- `read.iron_plate_line`: inspect the minimal iron plate line, including furnace fuel, input, output, plate count, and blocked reason.

## Action primitives

- `action.build_iron_plate_line`: build a deterministic minimal iron ore to iron plate furnace line and insert ore/fuel.
- `wait.seconds`: wait real time. Use `args={"seconds": 5}` for the iron plate line.

## Minimal iron plate line

Recommended flow:

1. `factorio_script(name="action.build_iron_plate_line")`
2. `factorio_script(name="wait.seconds", args={"seconds": 5})`
3. `factorio_script(name="read.iron_plate_line")`

Success is `total_iron_plates >= 10` or a stone furnace output inventory with
`iron-plate x10`. `recipe: none` is normal for stone furnaces.
"""
