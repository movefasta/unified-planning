# Copyright 2021 AIPlan4EU project
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

from itertools import product
import unified_planning as up
import unified_planning.model.htn as htn
import unified_planning.model.walkers
import typing
from unified_planning.model import ContingentProblem
from unified_planning.environment import Environment, get_environment
from unified_planning.exceptions import UPUsageError
from collections import OrderedDict
from fractions import Fraction
from typing import Dict, Union, Callable, List, cast

from pyparsing import Word, alphanums, alphas, ZeroOrMore, OneOrMore, Keyword
from pyparsing import Suppress, Group, rest_of_line, Optional, Forward
from pyparsing import CharsNotIn, Empty, Located, col, lineno
from pyparsing.results import ParseResults
from pyparsing import one_of


class CaseInsensitiveToken:
    """A case-insensitive representation of a string."""

    def __init__(self, name: Union[str, ParseResults]):
        if isinstance(name, ParseResults):
            name = name[0]
        assert isinstance(name, str)
        self._name = name
        self._canonical = name.lower()

    def __repr__(self):
        return self._name

    def __hash__(self):
        return hash(self._canonical)

    def __eq__(self, other):
        if isinstance(other, str):
            return other.lower() == self._canonical
        elif isinstance(other, CaseInsensitiveToken):
            return self._canonical == other._canonical
        else:
            return False


class CustomParseResults:
    def __init__(self, r):
        self.res = r
        self.value = r.value
        self.locn_start = r.locn_start
        self.locn_end = r.locn_end
        if len(self.value) == 1 and isinstance(self.value[0], str):
            self.value = self.value[0]

    def __getitem__(self, i):
        return CustomParseResults(self.value[i])

    def __len__(self):
        return len(self.value)

    def line_start(self, complete_str: str) -> int:
        return lineno(self.locn_start, complete_str)

    def col_start(self, complete_str: str) -> int:
        return col(self.locn_start, complete_str)

    def line_end(self, complete_str: str) -> int:
        return lineno(self.locn_end, complete_str)

    def col_end(self, complete_str: str) -> int:
        return col(self.locn_end, complete_str)


Object = CaseInsensitiveToken("object")
TypesMap = Dict[CaseInsensitiveToken, unified_planning.model.Type]


def nested_expr():
    """
    A hand-rolled alternative to pyparsing.nested_expr() that substantially improves its performance in our case.
    """
    cnt = Empty() + CharsNotIn("() \n\t\r")
    nested = Forward()
    nested <<= Group(
        Located(
            Suppress("(") + ZeroOrMore(Group(Located(cnt)) | nested) + Suppress(")")
        )
    )
    return nested


class PDDLGrammar:
    def __init__(self):
        name = Word(alphas, alphanums + "_" + "-")
        # Parser for types that convert the string into a token that is case-insensitive
        tpe = name.copy().add_parse_action(lambda t: CaseInsensitiveToken(t))
        variable = Suppress("?") + name

        require_def = (
            Suppress("(")
            + ":requirements"
            + OneOrMore(
                one_of(
                    ":strips :typing :negative-preconditions :disjunctive-preconditions :equality :existential-preconditions :universal-preconditions :quantified-preconditions :conditional-effects :fluents :numeric-fluents :adl :durative-actions :duration-inequalities :timed-initial-literals :action-costs :hierarchy :method-preconditions :constraints :contingent :preferences"
                )
            )
            + Suppress(")")
        )

        types_def = (
            Suppress("(")
            + ":types"
            - OneOrMore(
                Group(Group(OneOrMore(tpe)) + Optional(Suppress("-") + tpe))
            ).setResultsName("types")
            + Suppress(")")
        )

        constants_def = (
            Suppress("(")
            + ":constants"
            - ZeroOrMore(
                Group(Located(Group(OneOrMore(name)) + Optional(Suppress("-") + tpe)))
            ).setResultsName("constants")
            + Suppress(")")
        )

        predicate = (
            Suppress("(")
            + Group(
                name
                + Group(
                    ZeroOrMore(
                        Group(
                            Located(
                                Group(OneOrMore(variable))
                                + Optional(Suppress("-") + tpe)
                            )
                        )
                    )
                )
            )
            + Suppress(")")
        )

        predicates_def = (
            Suppress("(")
            + ":predicates"
            - Group(OneOrMore(predicate)).setResultsName("predicates")
            + Suppress(")")
        )

        functions_def = (
            Suppress("(")
            + ":functions"
            - Group(
                OneOrMore(predicate + Optional(Suppress("- number")))
            ).setResultsName("functions")
            + Suppress(")")
        )

        parameters = ZeroOrMore(
            Group(Located(Group(OneOrMore(variable)) + Optional(Suppress("-") + tpe)))
        ).setResultsName("params")
        action_def = Group(
            Suppress("(")
            + ":action"
            - name.setResultsName("name")
            + ":parameters"
            - Suppress("(")
            + parameters
            + Suppress(")")
            + Optional(":precondition" - nested_expr().setResultsName("pre"))
            + Optional(":effect" - nested_expr().setResultsName("eff"))
            + Optional(":observe" - nested_expr().setResultsName("obs"))
            + Suppress(")")
        )

        dur_action_def = Group(
            Suppress("(")
            + ":durative-action"
            - name.setResultsName("name")
            + ":parameters"
            - Suppress("(")
            + parameters
            + Suppress(")")
            + ":duration"
            - nested_expr().setResultsName("duration")
            + ":condition"
            - nested_expr().setResultsName("cond")
            + ":effect"
            - nested_expr().setResultsName("eff")
            + Suppress(")")
        )

        task_def = Group(
            Suppress("(")
            + ":task"
            - name.setResultsName("name")
            + ":parameters"
            - Suppress("(")
            + parameters
            + Suppress(")")
            + Suppress(")")
        )

        method_def = Group(
            Suppress("(")
            + ":method"
            - name.setResultsName("name")
            + ":parameters"
            - Suppress("(")
            + parameters
            + Suppress(")")
            + ":task"
            - nested_expr().setResultsName("task")
            + Optional(":precondition" - nested_expr().setResultsName("precondition"))
            + Optional(
                one_of(":ordered-subtasks :ordered-tasks")
                - nested_expr().setResultsName("ordered-subtasks")
            )
            + Optional(
                one_of(":subtasks :tasks") - nested_expr().setResultsName("subtasks")
            )
            + Optional(":ordering" - nested_expr().setResultsName("ordering"))
            + Optional(":constraints" - nested_expr().setResultsName("constraints"))
            + Suppress(")")
        )

        domain = (
            Suppress("(")
            + "define"
            + Suppress("(")
            + "domain"
            + name.setResultsName("name")
            + Suppress(")")
            + Optional(require_def).setResultsName("features")
            + Optional(types_def)
            + Optional(constants_def)
            + Optional(predicates_def)
            + Optional(functions_def)
            + Group(ZeroOrMore(task_def)).setResultsName("tasks")
            + Group(ZeroOrMore(method_def)).setResultsName("methods")
            + Group(ZeroOrMore(action_def | dur_action_def)).setResultsName("actions")
            + Suppress(")")
        )

        objects = OneOrMore(
            Group(Group(OneOrMore(name)) + Optional(Suppress("-") + tpe))
        ).setResultsName("objects")

        htn_def = Group(
            Suppress("(")
            + ":htn"
            - Optional(":parameters" - Suppress("(") + parameters + Suppress(")"))
            + Optional(
                one_of(":ordered-tasks :ordered-subtasks")
                - nested_expr().setResultsName("ordered-tasks")
            )
            + Optional(
                one_of(":tasks :subtasks") - nested_expr().setResultsName("tasks")
            )
            + Optional(":ordering" - nested_expr().setResultsName("ordering"))
            + Optional(":constraints" - nested_expr().setResultsName("constraints"))
            + Suppress(")")
        )

        metric = (Keyword("minimize") | Keyword("maximize")).setResultsName(
            "optimization"
        ) + (name | nested_expr()).setResultsName("metric")

        problem = (
            Suppress("(")
            + "define"
            + Suppress("(")
            + "problem"
            + name.setResultsName("name")
            + Suppress(")")
            + Suppress("(")
            + ":domain"
            + name
            + Suppress(")")
            + Optional(require_def)
            + Optional(Suppress("(") + ":objects" + objects + Suppress(")"))
            + Optional(htn_def.setResultsName("htn"))
            + Suppress("(")
            + ":init"
            + ZeroOrMore(nested_expr()).setResultsName("init")
            + Suppress(")")
            + Optional(
                Suppress("(")
                + ":goal"
                + nested_expr().setResultsName("goal")
                + Suppress(")")
            )
            + Optional(
                Suppress("(")
                + ":constraints"
                + nested_expr().setResultsName("constraints")
                + Suppress(")")
            )
            + Optional(Suppress("(") + ":metric" + metric + Suppress(")"))
            + Suppress(")")
        )

        domain.ignore(";" + rest_of_line)
        problem.ignore(";" + rest_of_line)

        self._domain = domain
        self._problem = problem
        self._parameters = parameters

    @property
    def domain(self):
        return self._domain

    @property
    def problem(self):
        return self._problem

    @property
    def parameters(self):
        return self._parameters


class PDDLReader:
    """
    Parse a `PDDL` domain file and, optionally, a `PDDL` problem file and generate the equivalent :class:`~unified_planning.model.Problem`.

    Note: in the error report messages, a tabulation counts as one column.
    """

    def __init__(self, environment: typing.Optional[Environment] = None):
        self._env = get_environment(environment)
        self._em = self._env.expression_manager
        self._tm = self._env.type_manager
        self._operators: Dict[str, Callable] = {
            "and": self._em.And,
            "or": self._em.Or,
            "not": self._em.Not,
            "imply": self._em.Implies,
            ">=": self._em.GE,
            "<=": self._em.LE,
            ">": self._em.GT,
            "<": self._em.LT,
            "=": self._em.Equals,
            "+": self._em.Plus,
            "-": self._em.Minus,
            "/": self._em.Div,
            "*": self._em.Times,
        }
        self._trajectory_constraints: Dict[str, Callable] = {
            "always": self._em.Always,
            "sometime": self._em.Sometime,
            "sometime-before": self._em.SometimeBefore,
            "sometime-after": self._em.SometimeAfter,
            "at-most-once": self._em.AtMostOnce,
        }
        grammar = PDDLGrammar()
        self._pp_domain = grammar.domain
        self._pp_problem = grammar.problem
        self._pp_parameters = grammar.parameters
        self._fve = self._env.free_vars_extractor
        self._totalcost: typing.Optional[up.model.FNode] = None

    def _parse_exp(
        self,
        problem: up.model.Problem,
        act: typing.Optional[Union[up.model.Action, htn.Method, htn.TaskNetwork]],
        types_map: TypesMap,
        var: Dict[str, up.model.Variable],
        exp: CustomParseResults,
        complete_str: str,
        assignments: Dict[str, "up.model.Object"] = {},
    ) -> up.model.FNode:
        stack = [(var, exp, False)]
        solved: List[up.model.FNode] = []
        while len(stack) > 0:
            var, exp, status = stack.pop()
            if status:
                if exp[0].value == "-" and len(exp) == 2:  # unary minus
                    solved.append(self._em.Times(-1, solved.pop()))
                elif exp[0].value in self._operators:  # n-ary operators
                    op: Callable = self._operators[exp[0].value]
                    solved.append(op(*[solved.pop() for _ in range(1, len(exp))]))
                elif exp[0].value in ["exists", "forall"]:  # quantifier operators
                    q_op: Callable = (
                        self._em.Exists if exp[0].value == "exists" else self._em.Forall
                    )
                    solved.append(q_op(solved.pop(), *var.values()))
                elif (
                    exp[0].value in self._trajectory_constraints
                ):  # trajectory_constraints reference
                    t_op: Callable = self._trajectory_constraints[exp[0].value]
                    solved.append(t_op(*[solved.pop() for _ in range(1, len(exp))]))
                elif problem.has_fluent(exp[0].value):  # fluent reference
                    f = problem.fluent(exp[0].value)
                    args = [solved.pop() for _ in range(1, len(exp))]
                    try:
                        solved.append(self._em.FluentExp(f, tuple(args)))
                    except Exception as e:
                        start_line, start_col = exp.line_start(
                            complete_str
                        ), exp.col_start(complete_str)
                        end_line, end_col = exp.line_end(complete_str), exp.col_end(
                            complete_str
                        )
                        raise SyntaxError(
                            repr(e)
                            + f"\nError from line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
                        )
                elif exp[0].value in assignments:  # quantified assignment variable
                    assert len(exp) == 1
                    solved.append(self._em.ObjectExp(assignments[exp[0].value]))
                else:
                    start_line, start_col = exp.line_start(complete_str), exp.col_start(
                        complete_str
                    )
                    end_line, end_col = exp.line_end(complete_str), exp.col_end(
                        complete_str
                    )
                    raise up.exceptions.UPUnreachableCodeError(
                        f"Invalid expression from line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
                    )
            else:
                if isinstance(exp.value, ParseResults):
                    if len(exp) == 0:  # empty precodition
                        solved.append(self._em.TRUE())
                    elif exp[0].value == "-" and len(exp) == 2:  # unary minus
                        stack.append((var, exp, True))
                        stack.append((var, exp[1], False))
                    elif exp[0].value in self._operators:  # n-ary operators
                        stack.append((var, exp, True))
                        for i in range(1, len(exp)):
                            stack.append((var, exp[i], False))
                    elif exp[0].value in ["exists", "forall"]:  # quantifier operators
                        vars_string = " ".join([e.value for e in exp[1]])
                        vars_res = self._pp_parameters.parseString(vars_string)
                        new_vars = {}
                        for g in vars_res["params"]:
                            try:
                                t = types_map[
                                    g.value[1] if len(g.value) > 1 else Object
                                ]
                            except KeyError:
                                g_start_line, g_start_col = lineno(
                                    g.locn_start, complete_str
                                ), col(g.locn_start, complete_str)
                                g_end_line, g_end_col = lineno(
                                    g.locn_end, complete_str
                                ), col(g.locn_end, complete_str)
                                raise SyntaxError(
                                    f"Undefined variable's type: {g[1]}."
                                    + f"\nError from line: {g_start_line}, col: {g_start_col} to line: {g_end_line}, col: {g_end_col}."
                                )
                            for o in g.value[0]:
                                new_vars[o] = up.model.Variable(o, t, self._env)
                        # new_vars are the variables defined by the quantifier currently being solved
                        # all_vars are the variables defined by all the quantifiers around this expression
                        stack.append((new_vars, exp, True))
                        all_vars = var.copy()
                        all_vars.update(new_vars)
                        stack.append((all_vars, exp[2], False))
                    elif (
                        exp[0].value in self._trajectory_constraints
                    ):  # trajectory_constraints reference
                        stack.append((var, exp, True))
                        for i in range(1, len(exp)):
                            stack.append((var, exp[i], False))
                    elif problem.has_fluent(exp[0].value):  # fluent reference
                        stack.append((var, exp, True))
                        for i in range(1, len(exp)):
                            stack.append((var, exp[i], False))
                    elif exp[0].value in assignments:  # quantified assignment variable
                        assert len(exp) == 1
                        stack.append((var, exp, True))
                    elif len(exp) == 1:  # expand an element inside brackets
                        stack.append((var, exp[0], False))
                    else:
                        start_line, start_col = exp.line_start(
                            complete_str
                        ), exp.col_start(complete_str)
                        end_line, end_col = exp.line_end(complete_str), exp.col_end(
                            complete_str
                        )
                        raise SyntaxError(
                            f"Not able to handle: {complete_str[exp.locn_start: exp.locn_end]} found at line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
                        )
                elif isinstance(exp.value, str):
                    if (
                        exp.value[0] == "?" and exp.value[1:] in var
                    ):  # variable in a quantifier expression
                        solved.append(self._em.VariableExp(var[exp.value[1:]]))
                    elif exp.value in assignments:  # quantified assignment variable
                        solved.append(self._em.ObjectExp(assignments[exp.value]))
                    elif exp.value[0] == "?":  # action parameter
                        assert act is not None
                        try:
                            solved.append(
                                self._em.ParameterExp(act.parameter(exp.value[1:]))
                            )
                        except KeyError:
                            start_line, start_col = exp.line_start(
                                complete_str
                            ), exp.col_start(complete_str)
                            end_line, end_col = exp.line_end(complete_str), exp.col_end(
                                complete_str
                            )
                            raise SyntaxError(
                                f"Undefined name found: {exp.value[1:]}.\nError in expression from"
                                + f" line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
                            )
                    elif problem.has_fluent(exp.value):  # fluent
                        solved.append(self._em.FluentExp(problem.fluent(exp.value)))
                    elif problem.has_object(exp.value):  # object
                        solved.append(self._em.ObjectExp(problem.object(exp.value)))
                    else:  # number
                        try:
                            n = Fraction(exp.value)
                        except ValueError:
                            start_line, start_col = exp.line_start(
                                complete_str
                            ), exp.col_start(complete_str)
                            end_line, end_col = exp.line_end(complete_str), exp.col_end(
                                complete_str
                            )
                            raise SyntaxError(
                                f"Found invalid expression: {complete_str[exp.locn_start:exp.locn_end]}. From line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
                            )
                        if n.denominator == 1:
                            solved.append(self._em.Int(n.numerator))
                        else:
                            solved.append(self._em.Real(n))
                else:
                    start_line, start_col = exp.line_start(complete_str), exp.col_start(
                        complete_str
                    )
                    end_line, end_col = exp.line_end(complete_str), exp.col_end(
                        complete_str
                    )
                    raise SyntaxError(
                        f"Not able to handle: {exp}, from line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
                    )
        assert len(solved) == 1  # sanity check
        return solved.pop()

    def _add_effect(
        self,
        problem: up.model.Problem,
        act: Union[up.model.InstantaneousAction, up.model.DurativeAction],
        types_map: TypesMap,
        universal_assignments: typing.Optional[
            Dict["up.model.Action", List[CustomParseResults]]
        ],
        exp: CustomParseResults,
        complete_str: str,
        cond: Union[up.model.FNode, bool] = True,
        timing: typing.Optional[up.model.Timing] = None,
        assignments: Dict[str, "up.model.Object"] = {},
    ):
        to_add = [(exp, cond)]
        while to_add:
            exp, cond = to_add.pop(0)
            if len(exp) == 0:
                continue  # ignore the case where the effect list is empty, e.g., `:effect ()`
            op = exp[0].value
            if op == "and":
                for i in range(1, len(exp)):
                    to_add.append((exp[i], cond))
            elif op == "when":
                cond = self._parse_exp(
                    problem, act, types_map, {}, exp[1], complete_str, assignments
                )
                cond = cond.simplify()
                if not cond.is_false():
                    to_add.append((exp[2], cond))
            elif op == "not":
                exp = exp[1]
                eff = (
                    self._parse_exp(
                        problem, act, types_map, {}, exp, complete_str, assignments
                    ),
                    self._em.FALSE(),
                    cond,
                )
                act.add_effect(*eff if timing is None else (timing, *eff))  # type: ignore
            elif op == "assign":
                eff = (
                    self._parse_exp(
                        problem, act, types_map, {}, exp[1], complete_str, assignments
                    ),
                    self._parse_exp(
                        problem, act, types_map, {}, exp[2], complete_str, assignments
                    ),
                    cond,
                )
                act.add_effect(*eff if timing is None else (timing, *eff))  # type: ignore
            elif op == "increase":
                eff = (
                    self._parse_exp(
                        problem, act, types_map, {}, exp[1], complete_str, assignments
                    ),
                    self._parse_exp(
                        problem, act, types_map, {}, exp[2], complete_str, assignments
                    ),
                    cond,
                )
                act.add_increase_effect(*eff if timing is None else (timing, *eff))  # type: ignore
            elif op == "decrease":
                eff = (
                    self._parse_exp(
                        problem, act, types_map, {}, exp[1], complete_str, assignments
                    ),
                    self._parse_exp(
                        problem, act, types_map, {}, exp[2], complete_str, assignments
                    ),
                    cond,
                )
                act.add_decrease_effect(*eff if timing is None else (timing, *eff))  # type: ignore
            elif op == "forall":
                assert isinstance(exp, CustomParseResults)
                # Get the list of universal_assignments linked to this action. If it does not exist, default it to the empty list
                assert universal_assignments is not None
                action_assignments = universal_assignments.setdefault(act, [])
                action_assignments.append(exp)
            else:
                eff = (
                    self._parse_exp(
                        problem, act, types_map, {}, exp, complete_str, assignments
                    ),
                    self._em.TRUE(),
                    cond,
                )
                act.add_effect(*eff if timing is None else (timing, *eff))  # type: ignore

    def _add_condition(
        self,
        problem: up.model.Problem,
        act: up.model.DurativeAction,
        exp: CustomParseResults,
        types_map: TypesMap,
        complete_str: str,
        vars: typing.Optional[Dict[str, up.model.Variable]] = None,
    ):
        to_add = [(exp, vars)]
        while to_add:
            exp, vars = to_add.pop(0)
            op = exp[0].value
            if op == "and":
                for i in range(1, len(exp)):
                    to_add.append((exp[i], vars))
            elif op == "forall":
                vars_string = " ".join([e.value for e in exp[1]])
                vars_res = self._pp_parameters.parseString(vars_string)
                if vars is None:
                    vars = {}
                for g in vars_res["params"]:
                    try:
                        t = types_map[g.value[1] if len(g.value) > 1 else Object]
                    except KeyError:
                        g_start_line, g_start_col = lineno(
                            g.locn_start, complete_str
                        ), col(g.locn_start, complete_str)
                        g_end_line, g_end_col = lineno(g.locn_end, complete_str), col(
                            g.locn_end, complete_str
                        )
                        raise SyntaxError(
                            f"Undefined variable's type: {g[1]}."
                            + f"\nError from line: {g_start_line}, col: {g_start_col} to line: {g_end_line}, col: {g_end_col}."
                        )
                    for o in g.value[0]:
                        vars[o] = up.model.Variable(o, t, self._env)
                to_add.append((exp[2], vars))
            elif len(exp) == 3 and op == "at" and exp[1].value == "start":
                cond = self._parse_exp(
                    problem,
                    act,
                    types_map,
                    {} if vars is None else vars,
                    exp[2],
                    complete_str,
                )
                if vars is not None:
                    cond = self._em.Forall(cond, *vars.values())
                act.add_condition(up.model.StartTiming(), cond)
            elif len(exp) == 3 and op == "at" and exp[1].value == "end":
                cond = self._parse_exp(
                    problem,
                    act,
                    types_map,
                    {} if vars is None else vars,
                    exp[2],
                    complete_str,
                )
                if vars is not None:
                    cond = self._em.Forall(cond, *vars.values())
                act.add_condition(up.model.EndTiming(), cond)
            elif len(exp) == 3 and op == "over" and exp[1].value == "all":
                t_all = up.model.OpenTimeInterval(
                    up.model.StartTiming(), up.model.EndTiming()
                )
                cond = self._parse_exp(
                    problem,
                    act,
                    types_map,
                    {} if vars is None else vars,
                    exp[2],
                    complete_str,
                )
                if vars is not None:
                    cond = self._em.Forall(cond, *vars.values())
                act.add_condition(t_all, cond)
            else:
                start_line, start_col = exp.line_start(complete_str), exp.col_start(
                    complete_str
                )
                end_line, end_col = exp.line_end(complete_str), exp.col_end(
                    complete_str
                )
                raise SyntaxError(
                    f"Not able to handle: {exp}, from line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
                )

    def _add_timed_effects(
        self,
        problem: up.model.Problem,
        act: up.model.DurativeAction,
        types_map: TypesMap,
        universal_assignments: typing.Optional[
            Dict["up.model.Action", List[CustomParseResults]]
        ],
        eff: CustomParseResults,
        complete_str: str,
        assignments: Dict[str, "up.model.Object"] = {},
    ):
        to_add = [eff]
        while to_add:
            eff = to_add.pop(0)
            op = eff[0].value
            if op == "and":
                for i in range(1, len(eff)):
                    to_add.append(eff[i])
            elif len(eff) == 3 and op == "at" and eff[1].value == "start":
                self._add_effect(
                    problem,
                    act,
                    types_map,
                    universal_assignments,
                    eff[2],
                    complete_str,
                    timing=up.model.StartTiming(),
                    assignments=assignments,
                )
            elif len(eff) == 3 and op == "at" and eff[1].value == "end":
                self._add_effect(
                    problem,
                    act,
                    types_map,
                    universal_assignments,
                    eff[2],
                    complete_str,
                    timing=up.model.EndTiming(),
                    assignments=assignments,
                )
            elif len(eff) == 3 and op == "forall":
                assert universal_assignments is not None
                action_assignments = universal_assignments.setdefault(act, [])
                action_assignments.append(eff)
            else:
                start_line, start_col = eff.line_start(complete_str), eff.col_start(
                    complete_str
                )
                end_line, end_col = eff.line_end(complete_str), eff.col_end(
                    complete_str
                )
                raise SyntaxError(
                    f"Not able to handle: {eff}, from line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
                )

    def _parse_subtask(
        self,
        e,
        method: typing.Optional[Union[htn.Method, htn.TaskNetwork]],
        problem: htn.HierarchicalProblem,
        types_map: TypesMap,
        complete_str: str,
    ) -> typing.Optional[htn.Subtask]:
        """Returns the Subtask corresponding to the given expression e or
        None if the expression cannot be interpreted as a subtask."""
        if len(e) == 0:
            return None

        task_name = e[0].value
        if problem.has_task(task_name) or problem.has_action(task_name):
            # check the form '(task_name param1 param2...)'
            task: Union[htn.Task, up.model.Action]
            if problem.has_task(task_name):
                task = problem.get_task(task_name)
            else:
                task = problem.action(task_name)
            assert isinstance(task, htn.Task) or isinstance(task, up.model.Action)
            parameters = [
                self._parse_exp(problem, method, types_map, {}, e[i], complete_str)
                for i in range(1, len(e))
            ]
            return htn.Subtask(task, *parameters)
        elif len(e) == 2 and e[0].value != "and":
            # check the form "(task_id (task param1 param2...))"
            task_id = e[0].value
            subtask = self._parse_subtask(
                e[1], method, problem, types_map, complete_str
            )
            if subtask is not None:
                # the second element of the list is a valid subtask,
                # return the subtask, with the given identifier
                return htn.Subtask(subtask.task, *subtask.parameters, ident=task_id)
            else:
                return None
        else:
            return None

    def _parse_subtasks(
        self,
        e: CustomParseResults,
        method: typing.Optional[Union[htn.Method, htn.TaskNetwork]],
        problem: htn.HierarchicalProblem,
        types_map: TypesMap,
        complete_str: str,
    ) -> List[htn.Subtask]:
        """Returns the list of subtasks of the expression"""
        single_task = self._parse_subtask(e, method, problem, types_map, complete_str)
        if single_task is not None:
            return [single_task]
        elif len(e) == 0:
            return []
        elif e[0].value == "and":
            return [
                subtask
                for i in range(1, len(e))
                for subtask in self._parse_subtasks(
                    e[i], method, problem, types_map, complete_str
                )
            ]
        else:
            start_line, start_col = e.line_start(complete_str), e.col_start(
                complete_str
            )
            end_line, end_col = e.line_end(complete_str), e.col_end(complete_str)
            raise SyntaxError(
                f"Could not parse the subtasks list: {e}, from line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
            )

    def _check_if_object_type_is_needed(self, domain_res) -> bool:
        for p in domain_res.get("predicates", []):
            for g in p[1]:
                if len(g.value) <= 1 or g.value[1] == Object:
                    return True
        for p in domain_res.get("functions", []):
            for g in p[1]:
                if len(g.value) <= 1 or g.value[1] == Object:
                    return True
        for g in domain_res.get("constants", []):
            if len(g.value) <= 1 or g.value[1] == Object:
                return True
        for a in domain_res.get("actions", []):
            for g in a.get("params", []):
                if len(g.value) <= 1 or g.value[1] == Object:
                    return True
        for a in domain_res.get("tasks", []):
            for g in a.get("params", []):
                if len(g.value) <= 1 or g.value[1] == Object:
                    return True
        for a in domain_res.get("methods", []):
            for g in a.get("params", []):
                if len(g.value) <= 1 or g.value[1] == Object:
                    return True
        return False

    def _durative_action_has_cost(self, dur_act: up.model.DurativeAction):
        if self._totalcost in self._fve.get(
            dur_act.duration.lower
        ) or self._totalcost in self._fve.get(dur_act.duration.upper):
            return False
        for _, cl in dur_act.conditions.items():
            for c in cl:
                if self._totalcost in self._fve.get(c):
                    return False
        for _, el in dur_act.effects.items():
            for e in el:
                if (
                    self._totalcost in self._fve.get(e.fluent)
                    or self._totalcost in self._fve.get(e.value)
                    or self._totalcost in self._fve.get(e.condition)
                ):
                    return False
        return True

    def _instantaneous_action_has_cost(self, act: up.model.InstantaneousAction):
        for c in act.preconditions:
            if self._totalcost in self._fve.get(c):
                return False
        for e in act.effects:
            if self._totalcost in self._fve.get(
                e.value
            ) or self._totalcost in self._fve.get(e.condition):
                return False
            if e.fluent == self._totalcost:
                if (
                    not e.is_increase()
                    or not e.condition.is_true()
                    or not (e.value.is_int_constant() or e.value.is_real_constant())
                ):
                    return False
        return True

    def _problem_has_actions_cost(self, problem: up.model.Problem):
        if (
            self._totalcost is None
            or not problem.initial_value(self._totalcost).constant_value() == 0
        ):
            return False
        for _, el in problem.timed_effects.items():
            for e in el:
                if (
                    self._totalcost in self._fve.get(e.fluent)
                    or self._totalcost in self._fve.get(e.value)
                    or self._totalcost in self._fve.get(e.condition)
                ):
                    return False
        for c in problem.goals:
            if self._totalcost in self._fve.get(c):
                return False
        return True

    def _parse_problem(
        self,
        domain_res: ParseResults,
        domain_str: str,
        problem_res: typing.Optional[ParseResults],
        problem_str=typing.Optional[str],
    ) -> "up.model.Problem":
        problem: up.model.Problem
        if ":hierarchy" in set(domain_res.get("features", [])):
            problem = htn.HierarchicalProblem(
                domain_res["name"],
                self._env,
                initial_defaults={self._tm.BoolType(): self._em.FALSE()},
            )
        elif ":contingent" in set(domain_res.get("features", [])):
            problem = up.model.ContingentProblem(
                domain_res["name"],
                self._env,
                initial_defaults={self._tm.BoolType(): self._em.FALSE()},
            )
        else:
            problem = up.model.Problem(
                domain_res["name"],
                self._env,
                initial_defaults={self._tm.BoolType(): self._em.FALSE()},
            )

        types_map: TypesMap = {}
        object_type_needed: bool = self._check_if_object_type_is_needed(domain_res)
        universal_assignments: Dict["up.model.Action", List[CustomParseResults]] = {}

        # extract all type declarations into a dictionary
        type_declarations: Dict[
            CaseInsensitiveToken, typing.Optional[CaseInsensitiveToken]
        ] = {}
        for type_line in domain_res.get("types", []):
            father_name = (
                None if len(type_line) <= 1 else CaseInsensitiveToken(str(type_line[1]))
            )
            if father_name is None and object_type_needed:
                father_name = Object
            for declared_type in type_line[0]:
                declared_type = CaseInsensitiveToken(str(declared_type))
                if declared_type in type_declarations:
                    raise SyntaxError(
                        f"Type {declared_type} is declared more than once"
                    )
                type_declarations[declared_type] = father_name

        # Processes a type and adds it to the `types_map`.
        # If the father was not previously declared, it will be recursively declared as well.
        def declare_type(
            type: CaseInsensitiveToken,
            father_name: typing.Optional[CaseInsensitiveToken],
        ):
            if type in types_map:
                # type was already processed which might happen if it already appeared as the parent of another type
                return
            father: typing.Optional["up.model.Type"]
            if father_name is None:
                father = None
            elif father_name in types_map:
                father = types_map[father_name]
            elif father_name in type_declarations:
                # father exists but was not processed yet. Force processing immediately
                declare_type(father_name, type_declarations[father_name])
                father = types_map[father_name]
            elif father_name == Object and not object_type_needed:
                father = None
            else:  # not "object" and not explicitly declared
                father = self._env.type_manager.UserType(str(father_name), None)
                types_map[father_name] = father
            # we identified the father, add the type to our map
            # note that the type_map allows retrieving the `Type` object in a case-insensitive way
            types_map[type] = self._env.type_manager.UserType(str(type), father)
            # Force declaration of the type in the `Problem`, even if it is not explicitly used yet
            problem._add_user_type(types_map[type])

        # declare all types
        for declared_type, father_name in type_declarations.items():
            declare_type(declared_type, father_name)

        if object_type_needed and Object not in types_map:
            # The object type is needed, but has not been defined explicitly. We manually define it
            types_map[Object] = self._env.type_manager.UserType("object", None)

        has_actions_cost = False

        for p in domain_res.get("predicates", []):
            n = p[0]
            params = OrderedDict()
            for g in p[1]:
                try:
                    param_type = types_map[g.value[1] if len(g.value) > 1 else Object]
                except KeyError:
                    g_start_line, g_start_col = lineno(g.locn_start, domain_str), col(
                        g.locn_start, domain_str
                    )
                    g_end_line, g_end_col = lineno(g.locn_end, domain_str), col(
                        g.locn_end, domain_str
                    )
                    raise SyntaxError(
                        f"Undefined parameter's type: {g.value[1]}."
                        + f"\nError from line: {g_start_line}, col: {g_start_col} to line: {g_end_line}, col: {g_end_col}."
                    )
                for param_name in g.value[0]:
                    params[param_name] = param_type
            f = up.model.Fluent(n, self._tm.BoolType(), params, self._env)
            problem.add_fluent(f)

        for p in domain_res.get("functions", []):
            n = p[0]
            params = OrderedDict()
            for g in p[1]:
                g_start_line, g_start_col = lineno(g.locn_start, domain_str), col(
                    g.locn_start, domain_str
                )
                g_end_line, g_end_col = lineno(g.locn_end, domain_str), col(
                    g.locn_end, domain_str
                )
                try:
                    param_type = types_map[g.value[1] if len(g.value) > 1 else Object]
                except KeyError:
                    raise SyntaxError(
                        f"Undefined parameter's type: {g.value[1]}."
                        + f"\nError from line: {g_start_line}, col: {g_start_col} to line: {g_end_line}, col: {g_end_col}."
                    )
                for param_name in g.value[0]:
                    if param_name not in params:
                        params[param_name] = param_type
                    else:
                        g_start_line, g_start_col = lineno(
                            g.locn_start, domain_str
                        ), col(g.locn_start, domain_str)
                        g_end_line, g_end_col = lineno(g.locn_end, domain_str), col(
                            g.locn_end, domain_str
                        )
                        raise SyntaxError(
                            f"In definition of function {n} the parameter {param_name} "
                            + f"is defined twice.\nError from line: {g_start_line}, col: {g_start_col}"
                            + f" to line: {g_end_line}, col: {g_end_col}."
                        )
            f = up.model.Fluent(n, self._tm.RealType(), params, self._env)
            if n == "total-cost":
                has_actions_cost = True
                self._totalcost = cast(up.model.FNode, self._em.FluentExp(f))
            problem.add_fluent(f)

        for g in domain_res.get("constants", []):
            try:
                t = types_map[g.value[1] if len(g.value) > 1 else Object]
            except KeyError:
                g_start_line, g_start_col = lineno(g.locn_start, domain_str), col(
                    g.locn_start, domain_str
                )
                g_end_line, g_end_col = lineno(g.locn_end, domain_str), col(
                    g.locn_end, domain_str
                )
                raise SyntaxError(
                    f"Undefined variable's type: {g.value[1]}."
                    + f"\nError from line: {g_start_line}, col: {g_start_col} to line: {g_end_line}, col: {g_end_col}."
                )
            for o in g.value[0]:
                problem.add_object(up.model.Object(o, t, problem.environment))

        for task in domain_res.get("tasks", []):
            assert isinstance(problem, htn.HierarchicalProblem)
            name = task["name"]
            task_params = OrderedDict()
            for g in task.get("params", []):
                try:
                    t = types_map[g.value[1] if len(g.value) > 1 else Object]
                except KeyError:
                    g_start_line, g_start_col = lineno(g.locn_start, domain_str), col(
                        g.locn_start, domain_str
                    )
                    g_end_line, g_end_col = lineno(g.locn_end, domain_str), col(
                        g.locn_end, domain_str
                    )
                    raise SyntaxError(
                        f"Undefined parameter's type: {g.value[1]}."
                        + f"\nError from line: {g_start_line}, col: {g_start_col} to line: {g_end_line}, col: {g_end_col}."
                    )
                for p in g.value[0]:
                    task_params[p] = t
            task = htn.Task(name, task_params)
            problem.add_task(task)

        for a in domain_res.get("actions", []):
            n = a["name"]
            a_params = OrderedDict()
            for g in a.get("params", []):
                try:
                    t = types_map[g.value[1] if len(g.value) > 1 else Object]
                except KeyError:
                    g_start_line, g_start_col = lineno(g.locn_start, domain_str), col(
                        g.locn_start, domain_str
                    )
                    g_end_line, g_end_col = lineno(g.locn_end, domain_str), col(
                        g.locn_end, domain_str
                    )
                    raise SyntaxError(
                        f"Undefined parameter's type: {g.value[1]}."
                        + f"\nError from line: {g_start_line}, col: {g_start_col} to line: {g_end_line}, col: {g_end_col}."
                    )
                for p in g.value[0]:
                    a_params[p] = t
            if "duration" in a:
                dur_act = up.model.DurativeAction(n, a_params, self._env)
                dur = CustomParseResults(a["duration"][0])
                if dur[0].value == "=":
                    dur_act.set_fixed_duration(
                        self._parse_exp(
                            problem, dur_act, types_map, {}, dur[2], domain_str
                        )
                    )
                elif dur[0].value == "and":
                    upper = None
                    lower = None
                    for j in range(1, len(dur)):
                        if dur[j][0].value == ">=" and lower is None:
                            lower = self._parse_exp(
                                problem, dur_act, types_map, {}, dur[j][2], domain_str
                            )
                        elif dur[j][0].value == "<=" and upper is None:
                            upper = self._parse_exp(
                                problem, dur_act, types_map, {}, dur[j][2], domain_str
                            )
                        else:
                            raise SyntaxError(
                                f"Not able to handle duration constraint of action {n}"
                                + f"Line: {dur.line_start(domain_str)}, col: {dur.col_start(domain_str)}",
                            )
                    if lower is None or upper is None:
                        raise SyntaxError(
                            f"Not able to handle duration constraint of action {n}"
                            + f"Line: {dur.line_start(domain_str)}, col: {dur.col_start(domain_str)}",
                        )
                    d = up.model.ClosedDurationInterval(lower, upper)
                    dur_act.set_duration_constraint(d)
                else:
                    raise SyntaxError(
                        f"Not able to handle duration constraint of action {n}"
                        + f"Line: {dur.line_start(domain_str)}, col: {dur.col_start(domain_str)}",
                    )
                cond = CustomParseResults(a["cond"][0])
                self._add_condition(problem, dur_act, cond, types_map, domain_str)
                eff = CustomParseResults(a["eff"][0])
                self._add_timed_effects(
                    problem, dur_act, types_map, universal_assignments, eff, domain_str
                )
                problem.add_action(dur_act)
                has_actions_cost = has_actions_cost and self._durative_action_has_cost(
                    dur_act
                )
            else:
                act: typing.Optional[
                    Union[up.model.SensingAction, up.model.InstantaneousAction]
                ] = None
                if "obs" in a:
                    act = up.model.SensingAction(n, a_params, self._env)
                    obs_fluent = CustomParseResults(a["obs"][0])
                    if obs_fluent[0].value == "and":  # more than 1 fluent
                        for i in range(1, len(obs_fluent)):
                            act.add_observed_fluent(
                                self._parse_exp(
                                    problem,
                                    act,
                                    types_map,
                                    {},
                                    obs_fluent[i],
                                    domain_str,
                                )
                            )
                    else:
                        act.add_observed_fluent(
                            self._parse_exp(
                                problem, act, types_map, {}, obs_fluent, domain_str
                            )
                        )
                else:
                    act = up.model.InstantaneousAction(n, a_params, self._env)
                if "pre" in a:
                    act.add_precondition(
                        self._parse_exp(
                            problem,
                            act,
                            types_map,
                            {},
                            CustomParseResults(a["pre"][0]),
                            domain_str,
                        )
                    )
                if "eff" in a:
                    self._add_effect(
                        problem,
                        act,
                        types_map,
                        universal_assignments,
                        CustomParseResults(a["eff"][0]),
                        domain_str,
                    )
                problem.add_action(act)
                has_actions_cost = (
                    has_actions_cost and self._instantaneous_action_has_cost(act)
                )

        for m in domain_res.get("methods", []):
            assert isinstance(problem, htn.HierarchicalProblem)
            name = m["name"]
            method_params = OrderedDict()
            for g in m.get("params", []):
                t = types_map[g.value[1] if len(g.value) > 1 else Object]
                for p in g.value[0]:
                    method_params[p] = t

            method = htn.Method(name, method_params)
            achieved_task = CustomParseResults(m["task"][0])
            pnames = []
            for i in range(1, len(achieved_task)):
                pname = achieved_task[i].value
                if pname[0] != "?":
                    raise SyntaxError(
                        f"All arguments of the task {achieved_task} should be parameters."
                        + f"Line: {achieved_task.line_start(domain_str)}, col: {achieved_task.col_start(domain_str)}",
                    )
                pnames.append(pname)
            achieved_task_params = [method.parameter(pname[1:]) for pname in pnames]
            method.set_task(
                problem.get_task(achieved_task[0].value), *achieved_task_params
            )
            if "ordered-subtasks" in m:
                ost = CustomParseResults(m.get("ordered-subtasks")[0])
                ord_subs = self._parse_subtasks(
                    ost, method, problem, types_map, domain_str
                )
                for s in ord_subs:
                    method.add_subtask(s)
                method.set_ordered(*ord_subs)
            if "subtasks" in m:
                st = CustomParseResults(m.get("subtasks")[0])
                subs = self._parse_subtasks(st, method, problem, types_map, domain_str)
                for s in subs:
                    method.add_subtask(s)
            if "ordering" in m:
                stack = [CustomParseResults(m.get("ordering")[0])]
                while stack:
                    ordering = stack.pop(0)
                    if len(ordering) == 0:
                        pass
                    elif ordering[0].value == "and":
                        # add the rest of the expression to the queue
                        for i in range(1, len(ordering)):
                            stack.append(ordering[i])
                    elif ordering[0].value == "<":
                        if len(ordering) != 3:
                            raise SyntaxError(
                                f"Wrong number of parameters in ordering relation: {ordering}"
                                + f"Line: {ordering.line_start(domain_str)}, col: {ordering.col_start(domain_str)}",
                            )
                        left = method.get_subtask(ordering[1].value)
                        right = method.get_subtask(ordering[2].value)
                        method.set_strictly_before(left, right)
                    else:
                        raise SyntaxError(
                            f"Invalid expression in ordering, expected 'and' or '<' but got '{ordering[0]}"
                            + f"Line: {ordering.line_start(domain_str)}, col: {ordering.col_start(domain_str)}",
                        )
            if "precondition" in m:
                method.add_precondition(
                    self._parse_exp(
                        problem,
                        method,
                        types_map,
                        {},
                        CustomParseResults(m["precondition"][0]),
                        domain_str,
                    )
                )
            problem.add_method(method)

        if problem_res is not None:
            assert problem_str is not None
            problem.name = problem_res["name"]

            for g in problem_res.get("objects", []):
                t = types_map[g[1] if len(g) > 1 else Object]
                for o in g[0]:
                    problem.add_object(up.model.Object(o, t, problem.environment))

            for action, eff_list in universal_assignments.items():
                for eff in eff_list:
                    # Parse the variable definition part and create 2 lists, the first one with the variable names,
                    # the second one with the variable types.
                    vars_string = " ".join([e.value for e in eff[1]])
                    vars_res = self._pp_parameters.parseString(vars_string)
                    var_names: List[str] = []
                    var_types: List["up.model.Type"] = []
                    for g in vars_res["params"]:
                        t = types_map[g.value[1] if len(g.value) > 1 else Object]
                        for o in g.value[0]:
                            var_names.append(f"?{o}")
                            var_types.append(t)
                    # for each variable type, get all the objects of that type and calculate the cartesian
                    # product between all the given objects and iterate over them, changing the variable assignments
                    # in the added effect
                    for objects in product(*(problem.objects(t) for t in var_types)):
                        assert len(var_names) == len(objects)
                        assignments = {
                            name: obj for name, obj in zip(var_names, objects)
                        }
                        if isinstance(action, up.model.InstantaneousAction):
                            self._add_effect(
                                problem,
                                action,
                                types_map,
                                None,
                                eff[2],
                                domain_str,
                                assignments=assignments,
                            )
                        elif isinstance(action, up.model.DurativeAction):
                            self._add_timed_effects(
                                problem,
                                action,
                                types_map,
                                None,
                                eff[2],
                                domain_str,
                                assignments=assignments,
                            )
                        else:
                            raise NotImplementedError

            tasknet = problem_res.get("htn", None)
            if tasknet is not None:
                assert isinstance(problem, htn.HierarchicalProblem)

                for tn_variables in tasknet.get("params", []):
                    tn_var_type = types_map[
                        tn_variables.value[1] if len(tn_variables.value) > 1 else Object
                    ]
                    for tn_var_name in tn_variables.value[0]:
                        problem.task_network.add_variable(tn_var_name, tn_var_type)

                ta = tasknet.get("tasks", None)
                if ta:
                    subtasks = self._parse_subtasks(
                        CustomParseResults(ta[0]),
                        problem.task_network,
                        problem,
                        types_map,
                        problem_str,
                    )
                    for task in subtasks:
                        problem.task_network.add_subtask(task)

                ot = tasknet.get("ordered-tasks", None)
                if ot:
                    subtasks = self._parse_subtasks(
                        CustomParseResults(ot[0]),
                        problem.task_network,
                        problem,
                        types_map,
                        problem_str,
                    )
                    prev = None
                    for task in subtasks:
                        cur = problem.task_network.add_subtask(task)
                        if prev is not None:
                            problem.task_network.set_strictly_before(prev, cur)
                        prev = cur

                oq = tasknet.get("ordering", None)
                stack = []
                if oq:
                    stack.append(CustomParseResults(oq[0]))
                while len(stack) > 0:
                    ordering = stack.pop(0)
                    if len(ordering) == 0:
                        pass
                    elif ordering[0].value == "and":
                        # add the rest of the expression to the queue
                        for i in range(1, len(ordering)):
                            stack.append(ordering[i])
                    elif ordering[0].value == "<":
                        if len(ordering) != 3:
                            raise SyntaxError(
                                f"Wrong number of parameters in ordering relation: {ordering}"
                                + f"Line: {ordering.line_start(domain_str)}, col: {ordering.col_start(domain_str)}",
                            )
                        left = problem.task_network.get_subtask(ordering[1].value)
                        right = problem.task_network.get_subtask(ordering[2].value)
                        problem.task_network.set_strictly_before(left, right)
                    else:
                        raise SyntaxError(
                            f"Invalid expression in ordering, expected 'and' or '<' but got '{ordering[0]}"
                            + f"Line: {ordering.line_start(domain_str)}, col: {ordering.col_start(domain_str)}",
                        )

                cs = tasknet.get("constraints", None)
                if cs:
                    constraints = CustomParseResults(cs[0])
                    for i in range(len(constraints)):
                        constraint = constraints[i]
                        problem.task_network.add_constraint(
                            self._parse_exp(
                                problem,
                                problem.task_network,
                                types_map,
                                {},
                                constraint,
                                problem_str,
                            )
                        )

            init_list = problem_res.get("init", [])
            if len(init_list) == 1 and list(init_list[0].value[0].value) == ["and"]:
                init_list = init_list[0].value[1:]
            for j in init_list:
                init = CustomParseResults(j)
                operator = init[0].value
                if operator == "=":
                    problem.set_initial_value(
                        self._parse_exp(
                            problem, None, types_map, {}, init[1], problem_str
                        ),
                        self._parse_exp(
                            problem, None, types_map, {}, init[2], problem_str
                        ),
                    )
                elif (
                    len(init) == 3
                    and operator == "at"
                    and init[1].value.replace(".", "", 1).isdigit()
                ):
                    try:
                        ti = up.model.StartTiming(Fraction(init[1].value))
                    except ValueError:
                        start_line, start_col = init.line_start(
                            problem_str
                        ), init.col_start(problem_str)
                        end_line, end_col = init.line_end(problem_str), init.col_end(
                            problem_str
                        )
                        raise SyntaxError(
                            f"Expected number, found {init[1].value} in expression from line: {start_line}, col {start_col} to line: {end_line}, col {end_col}"
                        )
                    va = self._parse_exp(
                        problem, None, types_map, {}, init[2], problem_str
                    )
                    if va.is_fluent_exp():
                        problem.add_timed_effect(ti, va, self._em.TRUE())
                    elif va.is_not():
                        problem.add_timed_effect(ti, va.arg(0), self._em.FALSE())
                    elif va.is_equals():
                        problem.add_timed_effect(ti, va.arg(0), va.arg(1))
                    else:
                        raise SyntaxError(
                            f"Not able to handle this TIL {init}"
                            + f"Line: {init.line_start(problem_str)}, col: {init.col_start(problem_str)}",
                        )
                elif operator == "oneof":
                    assert isinstance(problem, ContingentProblem)
                    fluents = [
                        self._parse_exp(
                            problem, None, types_map, {}, init[x], problem_str
                        )
                        for x in range(1, len(init))
                    ]
                    problem.add_oneof_initial_constraint(fluents)
                elif operator == "or":
                    assert isinstance(problem, ContingentProblem)
                    fluents = [
                        self._parse_exp(
                            problem, None, types_map, {}, init[x], problem_str
                        )
                        for x in range(1, len(init))
                    ]
                    problem.add_or_initial_constraint(fluents)
                elif operator == "unknown":
                    assert isinstance(problem, ContingentProblem)
                    if len(init) != 2:
                        raise SyntaxError(
                            "`unknown` constraint requires exactly one argument."
                            + f"Line: {init.line_start(problem_str)}, col: {init.col_start(problem_str)}",
                        )
                    arg = self._parse_exp(
                        problem, None, types_map, {}, init[1], problem_str
                    )
                    problem.add_unknown_initial_constraint(arg)
                else:
                    problem.set_initial_value(
                        self._parse_exp(
                            problem, None, types_map, {}, init, problem_str
                        ),
                        self._em.TRUE(),
                    )

            if "goal" in problem_res:
                problem.add_goal(
                    self._parse_exp(
                        problem,
                        None,
                        types_map,
                        {},
                        CustomParseResults(problem_res["goal"][0]),
                        problem_str,
                    )
                )
            elif not isinstance(problem, htn.HierarchicalProblem):
                raise SyntaxError("Missing goal section in problem file.")

            if "constraints" in problem_res:
                problem.add_trajectory_constraint(
                    self._parse_exp(
                        problem,
                        None,
                        types_map,
                        {},
                        CustomParseResults(problem_res["constraints"][0]),
                        problem_str,
                    )
                )

            has_actions_cost = has_actions_cost and self._problem_has_actions_cost(
                problem
            )
            optimization = problem_res.get("optimization", None)
            m = problem_res.get("metric", None)

            if m is not None:
                metric = CustomParseResults(m[0])
                if (
                    optimization == "minimize"
                    and len(metric) == 1
                    and metric[0].value == "total-time"
                ):
                    problem.add_quality_metric(up.model.metrics.MinimizeMakespan())
                else:
                    metric_exp = self._parse_exp(
                        problem, None, types_map, {}, metric, problem_str
                    )
                    if (
                        has_actions_cost
                        and optimization == "minimize"
                        and metric_exp == self._totalcost
                    ):
                        costs = {}
                        problem._fluents.remove(self._totalcost.fluent())
                        if self._totalcost in problem._initial_value:
                            problem._initial_value.pop(self._totalcost)
                        use_plan_length = all(False for _ in problem.durative_actions)
                        for a in problem.instantaneous_actions:
                            cost = None
                            for e in a.effects:
                                if e.fluent == self._totalcost:
                                    cost = e
                                    break
                            if cost is not None:
                                costs[a] = cost.value
                                a._effects.remove(cost)
                                if cost.value != 1:
                                    use_plan_length = False
                            else:
                                use_plan_length = False
                        if use_plan_length:
                            problem.add_quality_metric(
                                up.model.metrics.MinimizeSequentialPlanLength()
                            )
                        else:
                            problem.add_quality_metric(
                                up.model.metrics.MinimizeActionCosts(
                                    costs, self._em.Int(0)
                                )
                            )
                    else:
                        if optimization == "minimize":
                            problem.add_quality_metric(
                                up.model.metrics.MinimizeExpressionOnFinalState(
                                    metric_exp
                                )
                            )
                        elif optimization == "maximize":
                            problem.add_quality_metric(
                                up.model.metrics.MaximizeExpressionOnFinalState(
                                    metric_exp
                                )
                            )
        else:
            if len(universal_assignments) != 0:
                raise UPUsageError(
                    "The domain has quantified assignments. In the unified_planning library this is compatible only if the problem is given and not only the domain."
                )
        return problem

    def parse_problem(
        self, domain_filename: str, problem_filename: typing.Optional[str] = None
    ) -> "up.model.Problem":
        """
        Takes in input a filename containing the `PDDL` domain and optionally a filename
        containing the `PDDL` problem and returns the parsed `Problem`.

        Note that if the `problem_filename` is `None`, an incomplete `Problem` will be returned.

        :param domain_filename: The path to the file containing the `PDDL` domain.
        :param problem_filename: Optionally the path to the file containing the `PDDL` problem.
        :return: The `Problem` parsed from the given pddl domain + problem.
        """
        with open(domain_filename, "r") as domain_file:
            domain_str = domain_file.read()

        problem_str = None
        if problem_filename is not None:
            with open(problem_filename, "r") as problem_file:
                problem_str = problem_file.read()

        return self.parse_problem_string(domain_str, problem_str)

    def parse_problem_string(
        self, domain_str: str, problem_str: typing.Optional[str] = None
    ) -> "up.model.Problem":
        """
        Takes in input a str representing the `PDDL` domain and optionally a str
        representing the `PDDL` problem and returns the parsed `Problem`.

        Note that if the `problem_str` is `None`, an incomplete `Problem` will be returned.

        :param domain_filename: The string representing the `PDDL` domain.
        :param problem_filename: Optionally the string representing the `PDDL` problem.
        :return: The `Problem` parsed from the given pddl domain + problem.
        """
        domain_str = domain_str.replace("\t", " ")
        domain_res = self._pp_domain.parse_string(domain_str, parse_all=True)

        if problem_str is not None:
            problem_str = problem_str.replace("\t", " ")
            problem_res = self._pp_problem.parse_string(problem_str, parse_all=True)
        else:
            problem_res = None

        return self._parse_problem(domain_res, domain_str, problem_res, problem_str)
