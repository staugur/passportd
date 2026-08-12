# -*- coding: utf-8 -*-
"""
Copyright 2021 Hiroshi.tao

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from flask import Blueprint

from ..libs.metrics import bp as metrics_bp
from .api import bp as api_bp
from .front import bp as front_bp
from .oidc import bp as oidc_bp

root = Blueprint("root", "root")
root.register_blueprint(api_bp, url_prefix="/api")
root.register_blueprint(front_bp, url_prefix="/")
root.register_blueprint(oidc_bp, url_prefix="/")
root.register_blueprint(metrics_bp, url_prefix="/")
