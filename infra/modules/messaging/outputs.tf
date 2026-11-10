output "namespace_id" {
  value = azurerm_servicebus_namespace.this.id
}

output "fully_qualified_namespace" {
  value = "${azurerm_servicebus_namespace.this.name}.servicebus.windows.net"
}

output "queue_id" {
  value = azurerm_servicebus_queue.tickets.id
}

output "queue_name" {
  value = azurerm_servicebus_queue.tickets.name
}
