from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session() as session:
        session_id = "scientific-stack-workflow"

        numpy_round = await session.call_tool(
            "python_exec",
            {
                "code": (
                    "import numpy as np\n"
                    "observations = np.array([13, 15, 14, 18, 20, 24], dtype=float)\n"
                    "print(int(observations.sum()))\n"
                    "print(round(float(observations.mean()), 3))\n"
                    "print(round(float(np.median(observations)), 3))\n"
                    "print(round(float(observations.std(ddof=0)), 3))\n"
                ),
            },
            meta={"client_id": session_id},
        )
        numpy_payload = tool_json(numpy_round)
        assert numpy_payload["execution_status"] == "success", numpy_payload
        assert numpy_payload["interpreter_output"].splitlines() == ["104", "17.333", "16.5", "3.815"]

        linear_algebra_round = await session.call_tool(
            "python_exec",
            {
                "code": (
                    "import numpy as np\n"
                    "design = np.array([[4.0, 2.0], [1.0, 3.0]])\n"
                    "targets = np.array([16.0, 13.0])\n"
                    "solution = np.linalg.solve(design, targets)\n"
                    "print(np.round(solution, 3))\n"
                    "print(round(float(np.dot(design[0], solution)), 3))\n"
                    "print(round(float(np.dot(design[1], solution)), 3))\n"
                ),
            },
            meta={"client_id": session_id},
        )
        linear_payload = tool_json(linear_algebra_round)
        assert linear_payload["execution_status"] == "success", linear_payload
        assert linear_payload["interpreter_output"].splitlines() == ["[2.2 3.6]", "16.0", "13.0"]

        scipy_round = await session.call_tool(
            "python_exec",
            {
                "code": (
                    "import scipy.integrate as integrate\n"
                    "import scipy.optimize as opt\n"
                    "root = opt.brentq(lambda x: x**3 - 2 * x - 5, 2, 3)\n"
                    "area, error = integrate.quad(lambda x: x**2, 0, 3)\n"
                    "print(round(root, 6))\n"
                    "print(round(area, 6))\n"
                    "print(round(error, 12))\n"
                ),
            },
            meta={"client_id": session_id},
        )
        scipy_payload = tool_json(scipy_round)
        assert scipy_payload["execution_status"] == "success", scipy_payload
        scipy_root, scipy_area, scipy_error = scipy_payload["interpreter_output"].splitlines()
        assert abs(float(scipy_root) - 2.094551) < 1e-6
        assert abs(float(scipy_area) - 9.0) < 1e-6
        assert float(scipy_error) < 1e-9

        sympy_round = await session.call_tool(
            "python_exec",
            {
                "code": (
                    "import sympy as sp\n"
                    "x = sp.Symbol('x')\n"
                    "expr = sp.expand((x + 2) * (x - 3))\n"
                    "derivative = sp.diff(x**3 + 2 * x**2 + x, x)\n"
                    "integral = sp.integrate(2 * x + 1, x)\n"
                    "solution = sp.solve(sp.Eq(x**2 - 5 * x + 6, 0), x)\n"
                    "print(expr)\n"
                    "print(derivative)\n"
                    "print(integral)\n"
                    "print(solution)\n"
                ),
            },
            meta={"client_id": session_id},
        )
        sympy_payload = tool_json(sympy_round)
        assert sympy_payload["execution_status"] == "success", sympy_payload
        assert sympy_payload["interpreter_output"].splitlines() == ["x**2 - x - 6", "3*x**2 + 4*x + 1", "x**2 + x", "[2, 3]"]

        state_reuse_round = await session.call_tool(
            "python_exec",
            {
                "code": (
                    "import numpy as np\n"
                    "print(int(observations.argmax()))\n"
                    "print(int(observations[-1]))\n"
                    "print(int(design.sum()))\n"
                    "print(int(targets.sum()))\n"
                ),
            },
            meta={"client_id": session_id},
        )
        state_payload = tool_json(state_reuse_round)
        assert state_payload["execution_status"] == "success", state_payload
        assert state_payload["interpreter_output"].splitlines() == ["5", "24", "10", "29"]


def test_mcp_stdio_scientific_stack_workflow() -> None:
    asyncio.run(scenario())
