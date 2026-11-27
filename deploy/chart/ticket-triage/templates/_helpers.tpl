{{/* The image, always by digest (the platform's admission policy wants a version; this chart wants the digest). */}}
{{- define "ticket-triage.image" -}}
{{- $digest := required "image.digest is required (sha256:...)" .Values.image.digest -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" $digest) -}}
{{- fail (printf "image.digest must be sha256:<64 hex>, got %q" $digest) -}}
{{- end -}}
{{ .Values.image.repository }}@{{ $digest }}
{{- end -}}

{{- define "ticket-triage.labels" -}}
app.kubernetes.io/name: ticket-triage
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "ticket-triage.selector" -}}
app.kubernetes.io/name: ticket-triage
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Pod Security "restricted", no Kubernetes API token (the platform's rules, D7 and D9 there). */}}
{{- define "ticket-triage.podSecurity" -}}
automountServiceAccountToken: false
enableServiceLinks: false
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{- define "ticket-triage.containerSecurity" -}}
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
{{- end -}}

{{/* A Functions host loading only the given functions. dict: root, functions, resources, ready (readiness path).
The host answers /admin/host/ping without a key; /api/health (anonymous) only once the Python worker has indexed. */}}
{{- define "ticket-triage.functionsPod" -}}
{{- $root := .root -}}
{{ include "ticket-triage.podSecurity" $root }}
containers:
  - name: functions
    image: {{ include "ticket-triage.image" $root }}
    imagePullPolicy: IfNotPresent
    ports:
      - name: http
        containerPort: 8080
    envFrom:
      - configMapRef:
          name: {{ $root.Release.Name }}-config
    env:
      {{- range $i, $name := .functions }}
      - name: AzureFunctionsJobHost__functions__{{ $i }}
        value: {{ $name | quote }}
      {{- end }}
      {{- range $root.Values.secretSettings.keys }}
      - name: {{ . }}
        valueFrom:
          secretKeyRef:
            name: {{ $root.Values.secretSettings.secretName }}
            key: {{ . }}
      {{- end }}
    securityContext:
      {{- include "ticket-triage.containerSecurity" $root | nindent 6 }}
    resources:
      {{- toYaml .resources | nindent 6 }}
    startupProbe:
      httpGet: { path: /admin/host/ping, port: http }
      periodSeconds: 5
      failureThreshold: 36
    readinessProbe:
      httpGet: { path: {{ .ready }}, port: http }
      periodSeconds: 10
    livenessProbe:
      httpGet: { path: /admin/host/ping, port: http }
      periodSeconds: 20
      timeoutSeconds: 5
    volumeMounts:
      - name: function-keys
        mountPath: /run/secrets/functions-keys
        readOnly: true
volumes:
  - name: function-keys
    secret:
      secretName: {{ $root.Values.functionKeys.secretName }}
{{- end -}}