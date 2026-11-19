# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

output "app_url" {
  description = "Primary HTTPS entry point for the IAP-protected vidgen-omni web studio."
  value       = var.lb_domain != "" ? "https://${var.lb_domain}" : "https://${google_compute_global_address.web.address}"
}

output "lb_ip" {
  description = "External HTTPS Load Balancer static IP address."
  value       = google_compute_global_address.web.address
}

output "backend_service" {
  description = "Backend service name protected by Identity-Aware Proxy (IAP)."
  value       = google_compute_backend_service.web.name
}

output "iap_audience" {
  description = "Expected x-goog-iap-jwt-assertion audience string."
  value       = local.iap_audience
}

output "showcase_bucket" {
  description = "GCS bucket storing generated video runs and showcase assets."
  value       = google_storage_bucket.showcase.name
}

output "runtime_service_account" {
  description = "Least-privilege Cloud Run runtime service account email."
  value       = google_service_account.runtime.email
}
