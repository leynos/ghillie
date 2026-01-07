{{/*
Expand the name of the chart.
*/}}
{{- define "ghillie.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this
(by the DNS naming spec). If release name contains chart name it will be used
as a full name.
*/}}
{{- define "ghillie.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "ghillie.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "ghillie.labels" -}}
helm.sh/chart: {{ include "ghillie.chart" . }}
{{ include "ghillie.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels used for pod selection.
*/}}
{{- define "ghillie.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ghillie.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use.
*/}}
{{- define "ghillie.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "ghillie.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Determine the secret name to use for envFrom.
Priority: existingSecretName > externalSecret target > fullname default
When using ExternalSecret, the secret it creates has the same name as fullname.
*/}}
{{- define "ghillie.secretName" -}}
{{- if .Values.secrets.existingSecretName }}
{{- .Values.secrets.existingSecretName }}
{{- else }}
{{- include "ghillie.fullname" . }}
{{- end }}
{{- end }}
