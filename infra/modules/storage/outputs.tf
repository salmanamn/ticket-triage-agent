output "account_id" {
  value = azurerm_storage_account.this.id
}

output "account_name" {
  value = azurerm_storage_account.this.name
}

output "primary_blob_endpoint" {
  value = azurerm_storage_account.this.primary_blob_endpoint
}

output "deployments_container_name" {
  value = azurerm_storage_container.deployments.name
}

output "deadletter_container_name" {
  value = azurerm_storage_container.deadletter.name
}

output "deadletter_container_id" {
  value = azurerm_storage_container.deadletter.id
}
