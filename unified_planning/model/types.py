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
"""This module defines all the types."""

import unified_planning
from fractions import Fraction
from typing import Iterator, Optional, Dict, Tuple, List
from unified_planning.exceptions import UPProblemDefinitionError, UPTypeError


class Type:
    """Basic class for representing a type."""

    def is_bool_type(self) -> bool:
        """Returns true iff is boolean type."""
        return False

    def is_user_type(self) -> bool:
        """Returns true iff is a user type."""
        return False

    def is_real_type(self) -> bool:
        """Returns true iff is real type."""
        return False

    def is_int_type(self) -> bool:
        """Returns true iff is integer type."""
        return False


class _BoolType(Type):
    """Represents the boolean type."""

    def __repr__(self) -> str:
        return 'bool'

    def is_bool_type(self) -> bool:
        """Returns true iff is boolean type."""
        return True


class _UserType(Type):
    """Represents the user type."""
    def __init__(self, name: str, father: Optional[Type] = None):
        Type.__init__(self)
        self._name = name
        if father is not None and (not father.is_user_type()):
            raise UPTypeError('father field of a UserType must be a UserType.')
        self._father = father

    def __repr__(self) -> str:
        return self._name if self._father is None else f'{self._name} - {self._father.name()}' # type: ignore

    def name(self) -> str:
        """Returns the type name."""
        return self._name

    def father(self) -> Optional[Type]:
        """Returns the type s father."""
        return self._father

    def is_user_type(self) -> bool:
        """Returns true iff is a user type."""
        return True


class _IntType(Type):
    def __init__(self, lower_bound: int = None, upper_bound: int = None):
        Type.__init__(self)
        self._lower_bound = lower_bound
        self._upper_bound = upper_bound

    def __repr__(self) -> str:
        b = []
        if (not self.lower_bound() is None) or (not self.upper_bound() is None):
            b.append('[')
            b.append('-inf' if self.lower_bound() is None else str(self.lower_bound()))
            b.append(', ')
            b.append('inf' if self.upper_bound() is None else str(self.upper_bound()))
            b.append(']')
        return 'integer' + ''.join(b)

    def lower_bound(self) -> Optional[int]:
        return self._lower_bound

    def upper_bound(self) -> Optional[int]:
        return self._upper_bound

    def is_int_type(self) -> bool:
        return True


class _RealType(Type):
    def __init__(self, lower_bound: Fraction = None, upper_bound: Fraction = None):
        Type.__init__(self)
        self._lower_bound = lower_bound
        self._upper_bound = upper_bound

    def __repr__(self) -> str:
        b = []
        if (not self.lower_bound() is None) or (not self.upper_bound() is None):
            b.append('[')
            b.append('-inf' if self.lower_bound() is None else str(self.lower_bound()))
            b.append(', ')
            b.append('inf' if self.upper_bound() is None else str(self.upper_bound()))
            b.append(']')
        return 'real' + ''.join(b)

    def lower_bound(self) -> Optional[Fraction]:
        return self._lower_bound

    def upper_bound(self) -> Optional[Fraction]:
        return self._upper_bound

    def is_real_type(self) -> bool:
        return True


BOOL = _BoolType()

class TypeManager:
    def __init__(self):
        self._bool = BOOL
        self._ints: Dict[Tuple[Optional[int], Optional[int]], Type] = {}
        self._reals: Dict[Tuple[Optional[Fraction], Optional[Fraction]], Type] = {}
        self._user_types: Dict[Tuple[str, Optional[Type]], Type] = {}

    def BoolType(self) -> Type:
        return self._bool

    def IntType(self, lower_bound: int = None, upper_bound: int = None) -> Type:
        k = (lower_bound, upper_bound)
        if k in self._ints:
            return self._ints[k]
        else:
            it = _IntType(lower_bound, upper_bound)
            self._ints[k] = it
            return it

    def RealType(self, lower_bound: Fraction = None, upper_bound: Fraction = None) -> Type:
        k = (lower_bound, upper_bound)
        if k in self._reals:
            return self._reals[k]
        else:
            rt = _RealType(lower_bound, upper_bound)
            self._reals[k] = rt
            return rt

    def UserType(self, name: str, father: Optional[Type] = None) -> Type:
        if (name, father) in self._user_types:
            return self._user_types[(name, father)]
        else:
            if father is not None:
                if any(ancestor.name() == name for ancestor in self.user_type_ancestors(father)): # type: ignore
                    raise UPTypeError('The name: {name} is already used in the UserType: {ancestor}. An UserType and one of his ancestors can not share the name.')
            ut = _UserType(name, father)
            self._user_types[(name, father)] = ut
            return ut
    
    def user_type_ancestors(self, user_type: Type) -> Iterator[Type]:
        '''Returns all the ancestors of the given UserType, including itself.'''
        if not user_type.is_user_type():
            raise UPTypeError('The function user_type_ancestors can be called only on UserTypes.')
        yield user_type
        father: Optional[Type] = user_type.father() # type: ignore
        while father is not None:
            yield father
            father = father.father() # type: ignore


def domain_size(problem: 'unified_planning.model.problem.Problem', typename: 'unified_planning.model.types.Type') -> int:
    '''Returns the domain size of the given type.'''
    if typename.is_bool_type():
        return 2
    elif typename.is_user_type():
        return len(list(problem.objects_hierarchy(typename)))
    elif typename.is_int_type():
        lb = typename.lower_bound() # type: ignore
        ub = typename.upper_bound() # type: ignore
        if lb is None or ub is None:
            raise UPProblemDefinitionError('Parameter not groundable!')
        return ub - lb
    else:
        raise UPProblemDefinitionError('Parameter not groundable!')

def domain_item(problem: 'unified_planning.model.problem.Problem', typename: 'unified_planning.model.types.Type', idx: int) -> 'unified_planning.model.fnode.FNode':
    '''Returns the ith domain item of the given type.'''
    if typename.is_bool_type():
        return problem._env.expression_manager.Bool(idx == 0)
    elif typename.is_user_type():
        return problem._env.expression_manager.ObjectExp(list(problem.objects_hierarchy(typename))[idx])
    elif typename.is_int_type():
        lb = typename.lower_bound() # type: ignore
        ub = typename.upper_bound() # type: ignore
        if lb is None or ub is None:
            raise UPProblemDefinitionError('Parameter not groundable!')
        return problem._env.expression_manager.Int(lb + idx)
    else:
        raise UPProblemDefinitionError('Parameter not groundable!')