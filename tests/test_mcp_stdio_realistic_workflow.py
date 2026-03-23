from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session() as session:
        session_id = "analysis-workflow"

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import numpy as np\nvalues = np.array([12, 15, 14, 19, 21])\nprint(values.mean())\nprint(values.max())",
                "session_id": session_id,
            },
        )
        payload = tool_json(result)
        assert payload["output"].splitlines() == ["16.2", "21"]

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import numpy as np\nweeks = np.array([1, 2, 3, 4, 5])\nvalues = np.array([12, 15, 14, 19, 21])\ncoef = np.polyfit(weeks, values, 1)\nprint(round(float(coef[0]), 3))\nprint(round(float(coef[1]), 3))",
                "session_id": session_id,
            },
        )
        payload = tool_json(result)
        slope, intercept = payload["output"].splitlines()
        assert float(slope) > 0
        assert float(intercept) > 0

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import sympy as sp\nprice, cost = sp.symbols('price cost')\nsolution = sp.solve(sp.Eq(price - cost, 3), price)\nprint(solution)\nprint(sp.solve(sp.Eq(price * 2, 30), price))",
                "session_id": session_id,
            },
        )
        payload = tool_json(result)
        assert "cost + 3" in payload["output"]
        assert "15" in payload["output"]

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import math\nmargin = 3\nunits = 250\nprint(math.ceil(units * margin))",
                "session_id": session_id,
            },
        )
        payload = tool_json(result)
        assert payload["output"] == "750\n"


def test_mcp_stdio_realistic_workflow() -> None:
    asyncio.run(scenario())
