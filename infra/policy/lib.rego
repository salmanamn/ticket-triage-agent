# Input: `terraform show -json <plan>`. Every `deny` is one violation; Conftest fails on any.
# Rules look at change.after (the planned values); values known only after apply can't be checked here.
package main

import rego.v1

# Every resource of a type that will exist after apply (create, update or unchanged).
resources(type) := [rc |
	some rc in input.resource_changes
	rc.type == type
	rc.change.after != null
]

# The central workspace from Project 1. Diagnostics and Application Insights must go there.
platform_workspace := "/resourceGroups/rg-slz-platform/providers/Microsoft.OperationalInsights/workspaces/log-slz-platform"

is_platform_workspace(id) if {
	is_string(id)
	endswith(id, platform_workspace)
}