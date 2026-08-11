{{- define "traffic.chart" -}}
{{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{- define "traffic.labels" -}}
app.kubernetes.io/part-of: traffic-violation-detection
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ include "traffic.chart" . }}
{{- end }}

{{- define "traffic.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.pod.name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "traffic.awsSecretName" -}}
{{- if .Values.aws.existingSecret -}}
{{ .Values.aws.existingSecret }}
{{- else -}}
{{ .Release.Name }}-aws-credentials
{{- end -}}
{{- end }}
