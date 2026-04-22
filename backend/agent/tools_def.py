
"""
backend/agent/tools_def.py
"""

SELECT_ROUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "select_and_package_routes",
        "description": "从候选路线列表中选择最终的两条，并为它们分别赋予名称和点评。",
        "parameters": {
            "type": "object",
            "properties": {
                "selections": {
                    "type": "array",
                    "description": "一个包含两条已选定路线信息的列表。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "selected_route_id": {
                                "type": "string",
                                "description": "选定的路线 ID (例如 'route_0')"
                            },
                            "route_name": {
                                "type": "string",
                                "description": "为这条路线起的名字"
                            },
                            "setter_commentary": {
                                "type": "string",
                                "description": "定线员对这条路线的点评"
                            }
                        },
                        "required": ["selected_route_id", "route_name", "setter_commentary"]
                    },
                    "minItems": 2,
                    "maxItems": 2
                }
            },
            "required": ["selections"]
        }
    }
}
