output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "app_identity" {
  value = {
    id           = azurerm_user_assigned_identity.app.id
    client_id    = azurerm_user_assigned_identity.app.client_id
    principal_id = azurerm_user_assigned_identity.app.principal_id
  }
}

output "storage_account_name" {
  value = module.storage.account_name
}

output "eventgrid_topic_endpoint" {
  value = try(module.events[0].topic_endpoint, null)
}

output "servicebus_namespace" {
  value = try(module.messaging[0].fully_qualified_namespace, null)
}

output "cosmos_endpoint" {
  value = try(module.cosmos[0].endpoint, null)
}

output "function_app_name" {
  value = try(module.functionapp[0].name, null)
}

output "function_app_hostname" {
  value = try(module.functionapp[0].default_hostname, null)
}

# Names only (values are endpoints and ids). The Function App's app_settings are unknown in a plan
# (azurerm can't plan a map with any unknown value), so the policy gate checks these names instead.
output "app_setting_names" {
  value = var.components.function_app ? module.functionapp[0].app_setting_names : sort(keys(local.app_settings))
}
