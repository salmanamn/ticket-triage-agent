output "account_id" {
  value = azurerm_storage_account.this.id
}

output "account_name" {
  value = azurerm_storage_account.this.name
}

output "primary_blob_endpoint" {
  value = azurerm_storage_account.this.primary_blob_endpoint
}

# name => name, read from the created containers: whoever uses a name waits for its container.
output "container_names" {
  value = { for key, container in azurerm_storage_container.this : key => container.name }
}
