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

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  services = [
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iap.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
    "texttospeech.googleapis.com",
  ]

  runtime_roles = [
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/serviceusage.serviceUsageConsumer",
  ]

  effective_image = var.container_image != "" ? var.container_image : "${var.data_location}-docker.pkg.dev/${var.project_id}/${var.artifact_repo}/${var.service_name}:latest"
  secret_project  = var.secret_stored_project != "" ? var.secret_stored_project : var.project_id
  iap_audience    = "/projects/${data.google_project.current.number}/global/backendServices/${google_compute_backend_service.web.generated_id}"
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.services)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# Least-privilege runtime service account for Cloud Run
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "${var.service_name}-runtime"
  display_name = "vidgen-omni Cloud Run Runtime SA"
  depends_on   = [google_project_service.enabled]
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = toset(local.runtime_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

# Artifact Registry repository for container images
resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.data_location
  repository_id = var.artifact_repo
  format        = "DOCKER"
  description   = "Container images for vidgen-omni"
  depends_on    = [google_project_service.enabled]
}

# GCS bucket for showcase video artifacts and generated clips
resource "google_storage_bucket" "showcase" {
  project                     = var.project_id
  name                        = "${var.project_id}-vidgen-showcase"
  location                    = var.data_location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true
  depends_on                  = [google_project_service.enabled]
}

resource "google_storage_bucket_iam_member" "runtime_showcase_admin" {
  bucket = google_storage_bucket.showcase.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

# Dynamic session secret stored in Secret Manager (no hardcoded credentials)
resource "random_password" "app_session_secret" {
  length  = 32
  special = false
}

resource "google_secret_manager_secret" "app_session_secret" {
  project   = local.secret_project
  secret_id = "${var.service_name}-session-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "app_session_secret" {
  secret      = google_secret_manager_secret.app_session_secret.id
  secret_data = random_password.app_session_secret.result
}

resource "google_secret_manager_secret_iam_member" "runtime_secret_accessor" {
  project   = local.secret_project
  secret_id = google_secret_manager_secret.app_session_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# Cloud Run v2 service with Argolis-compliant LB-only ingress
resource "google_cloud_run_v2_service" "web" {
  project             = var.project_id
  name                = var.service_name
  location            = var.data_location
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account  = google_service_account.runtime.email
    timeout          = "3600s"
    session_affinity = true

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = local.effective_image

      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }

      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }

      env {
        name  = "GCS_SHOWCASE_BUCKET"
        value = google_storage_bucket.showcase.name
      }

      env {
        name  = "IAP_EXPECTED_AUDIENCE"
        value = local.iap_audience
      }

      env {
        name = "APP_SESSION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app_session_secret.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.runtime_roles,
    google_secret_manager_secret_iam_member.runtime_secret_accessor,
  ]
}

# Grant Cloud Run invoker exclusively to the IAP service agent (never allUsers)
resource "google_project_service_identity" "iap" {
  provider   = google-beta
  project    = var.project_id
  service    = "iap.googleapis.com"
  depends_on = [google_project_service.enabled]
}

resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_project_service_identity.iap.email}"
}

# External HTTPS Application Load Balancer + Serverless NEG + Backend IAP
resource "google_compute_global_address" "web" {
  project    = var.project_id
  name       = "${var.service_name}-ip"
  depends_on = [google_project_service.enabled]
}

resource "google_compute_region_network_endpoint_group" "web" {
  project               = var.project_id
  name                  = "${var.service_name}-neg"
  region                = var.data_location
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = var.service_name
  }

  depends_on = [google_project_service.enabled]
}

resource "google_compute_backend_service" "web" {
  project               = var.project_id
  name                  = "${var.service_name}-backend"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"
  timeout_sec           = 3600

  backend {
    group = google_compute_region_network_endpoint_group.web.id
  }

  # Preserve platform/CDP-managed IAP configuration across Terraform applies
  lifecycle {
    ignore_changes = [iap]
  }
}

resource "google_compute_url_map" "web" {
  project         = var.project_id
  name            = "${var.service_name}-urlmap"
  default_service = google_compute_backend_service.web.id
}

resource "google_compute_managed_ssl_certificate" "web" {
  count   = var.lb_domain != "" ? 1 : 0
  project = var.project_id
  name    = "${var.service_name}-cert"

  managed {
    domains = [var.lb_domain]
  }

  depends_on = [google_project_service.enabled]
}

resource "tls_private_key" "fallback" {
  count     = var.lb_domain == "" ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "fallback" {
  count           = var.lb_domain == "" ? 1 : 0
  private_key_pem = tls_private_key.fallback[0].private_key_pem

  subject {
    common_name  = "${var.service_name}.internal"
    organization = "vidgen-omni"
  }

  validity_period_hours = 8760

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

resource "google_compute_ssl_certificate" "fallback" {
  count       = var.lb_domain == "" ? 1 : 0
  project     = var.project_id
  name        = "${var.service_name}-self-signed-cert"
  private_key = tls_private_key.fallback[0].private_key_pem
  certificate = tls_self_signed_cert.fallback[0].cert_pem
  depends_on  = [google_project_service.enabled]
}

resource "google_compute_target_https_proxy" "web" {
  project = var.project_id
  name    = "${var.service_name}-https-proxy"
  url_map = google_compute_url_map.web.id
  ssl_certificates = [
    var.lb_domain != "" ? google_compute_managed_ssl_certificate.web[0].id : google_compute_ssl_certificate.fallback[0].id
  ]
}

resource "google_compute_global_forwarding_rule" "https" {
  project               = var.project_id
  name                  = "${var.service_name}-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.web.id
  port_range            = "443"
  target                = google_compute_target_https_proxy.web.id
}

resource "google_compute_url_map" "redirect" {
  project = var.project_id
  name    = "${var.service_name}-http-redirect"

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }

  depends_on = [google_project_service.enabled]
}

resource "google_compute_target_http_proxy" "redirect" {
  project = var.project_id
  name    = "${var.service_name}-http-proxy"
  url_map = google_compute_url_map.redirect.id
}

resource "google_compute_global_forwarding_rule" "http" {
  project               = var.project_id
  name                  = "${var.service_name}-http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.web.id
  port_range            = "80"
  target                = google_compute_target_http_proxy.redirect.id
}
