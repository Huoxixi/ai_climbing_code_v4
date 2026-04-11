
"""
backend/agent/tools_def.py
"""

SELECT_ROUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "select_and_package_route",
        "description": "从候选路线中选择最完美的一条，并赋予路线名称和定线员寄语。",
        "parameters": {
            "type": "object",
            "properties": {
                "selected_route_id": {
                    "type": "string",
                    "description": "选定的路线 ID"
                },
                "route_name": {
                    "type": "string",
                    "description": "为这条路线起的名字"
                },
                "setter_commentary": {
                    "type": "string",
                    "description": "定线员寄语，解释为什么选择这条路线"
                }
            },
            "required": ["selected_route_id", "route_name", "setter_commentary"]
        }
    }
}
