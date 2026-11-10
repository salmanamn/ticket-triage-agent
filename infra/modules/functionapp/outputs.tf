output "id" {
  value = azurerm_function_app_flex_consumption.this.id
}

output "name" {
  value = azurerm_function_app_flex_consumption.this.name
}

output "default_hostname" {
  value = azurerm_function_app_flex_consumption.this.default_hostname
}

output "app_setting_names" {
  value = sort(keys(merge(var.app_settings, local.host_settings)))
}
