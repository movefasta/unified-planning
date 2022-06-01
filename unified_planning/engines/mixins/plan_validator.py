# Copyright 2022 AIPlan4EU project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import unified_planning as up


class PlanValidatorMixin:

    @staticmethod
    def is_plan_validator() -> bool:
        return True

    def validate(self, problem: 'up.model.AbstractProblem', plan: 'up.plan.Plan') -> 'up.engines.results.ValidationResult':
        raise NotImplementedError
