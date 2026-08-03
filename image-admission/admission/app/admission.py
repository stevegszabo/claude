import os
import base64
import logging
import jsonpatch

from flask import Flask
from flask import request
from flask import jsonify

ADMISSION_CFG_LOG_LEVEL = os.environ.get("ADMISSION_LOG_LEVEL", "debug").lower()
ADMISSION_CFG_SECURITY_POLICY_MODE = os.environ.get("ADMISSION_SECURITY_POLICY_MODE", "privileged").lower()
ADMISSION_CFG_SECURITY_POLICY_VERSION = os.environ.get("ADMISSION_SECURITY_POLICY_VERSION", "latest").lower()
ADMISSION_CFG_ISTIO_INJECTION_MODE = os.environ.get("ADMISSION_ISTIO_INJECTION_MODE", "disabled").lower()
ADMISSION_CFG_EXEMPT_NAMESPACES_FILENAME = os.environ.get("ADMISSION_EXEMPT_NAMESPACES", "namespaces.exempt")
ADMISSION_CFG_EXEMPT_NAMESPACES = []

controller = Flask(__name__)
controller.logger.setLevel(level=logging.DEBUG)

if ADMISSION_CFG_LOG_LEVEL == "info":
    controller.logger.setLevel(level=logging.INFO)
elif ADMISSION_CFG_LOG_LEVEL == "warning":
    controller.logger.setLevel(level=logging.WARNING)
elif ADMISSION_CFG_LOG_LEVEL == "error":
    controller.logger.setLevel(level=logging.ERROR)
elif ADMISSION_CFG_LOG_LEVEL == "critical":
    controller.logger.setLevel(level=logging.CRITICAL)

controller.logger.debug(f"ADMISSION_CFG_LOG_LEVEL: [{ADMISSION_CFG_LOG_LEVEL}]")
controller.logger.debug(f"ADMISSION_CFG_SECURITY_POLICY_MODE: [{ADMISSION_CFG_SECURITY_POLICY_MODE}]")
controller.logger.debug(f"ADMISSION_CFG_SECURITY_POLICY_VERSION: [{ADMISSION_CFG_SECURITY_POLICY_VERSION}]")
controller.logger.debug(f"ADMISSION_CFG_ISTIO_INJECTION_MODE: [{ADMISSION_CFG_ISTIO_INJECTION_MODE}]")
controller.logger.debug(f"ADMISSION_CFG_EXEMPT_NAMESPACES_FILENAME: [{ADMISSION_CFG_EXEMPT_NAMESPACES_FILENAME}]")

with open(ADMISSION_CFG_EXEMPT_NAMESPACES_FILENAME) as handle:
    for item in handle:
        controller.logger.debug(f"Exempt namespace: [{item.rstrip()}]")
        ADMISSION_CFG_EXEMPT_NAMESPACES.append(item.rstrip())


def respond(allowed, uid, message, patches=None):
    response = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": uid,
            "allowed": allowed,
            "status": {"message": message}
        }
    }

    if patches:
        patch = jsonpatch.JsonPatch(patches).to_string().encode("utf-8")
        response["response"]["patch"] = base64.b64encode(patch).decode("utf-8")
        response["response"]["patchType"] = "JSONPatch"

    return jsonify(response)


@controller.route(rule="/mutate", methods=["POST"])
def mutate():
    request_json = request.get_json()
    request_kind = request_json["request"]["kind"]["kind"]
    request_name = request_json["request"]["name"]
    request_operation = request_json["request"]["operation"]
    request_uid = request_json["request"]["uid"]

    response = {
        "uid": request_uid,
        "allowed": True,
        "patches": [],
        "message": f"Mutated: [{request_kind}][{request_name}]"
    }

    if request_kind != "Namespace":
        controller.logger.debug(f"Ignoring resource: [{request_kind}][{request_name}][{request_operation}][{request_uid}]")
        return respond(**response)

    if request_name in ADMISSION_CFG_EXEMPT_NAMESPACES:
        controller.logger.debug(f"Ignoring namespace: [{request_kind}][{request_name}][{request_operation}][{request_uid}]")
        return respond(**response)

    if request_operation not in ["CREATE", "UPDATE"]:
        controller.logger.debug(f"Ignoring operation: [{request_kind}][{request_name}][{request_operation}][{request_uid}]")
        return respond(**response)

    if "labels" not in request_json["request"]["object"]["metadata"]:
        response["patches"].append({
            "op": "add",
            "path": "/metadata/labels",
            "value": {}
        })

    response["patches"].append({
        "op": "add",
        "path": "/metadata/labels/pod-security.kubernetes.io~1enforce",
        "value": ADMISSION_CFG_SECURITY_POLICY_MODE
    })

    response["patches"].append({
        "op": "add",
        "path": "/metadata/labels/pod-security.kubernetes.io~1enforce-version",
        "value": ADMISSION_CFG_SECURITY_POLICY_VERSION
    })

    response["patches"].append({
        "op": "add",
        "path": "/metadata/labels/istio-injection",
        "value": ADMISSION_CFG_ISTIO_INJECTION_MODE
    })

    return respond(**response)


@controller.route(rule="/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})


if __name__ == "__main__":
    controller.run(host="0.0.0.0", port=8443)
