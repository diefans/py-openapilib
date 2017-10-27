import logging
from typing import Optional, Union, Any, List, Dict

import attr
import deepdiff
import stringcase

from openapilib.helpers import LazyPretty
from openapilib.spec import (
    Components,
    SKIP,
    OpenAPI,
    T_Component,
)
from openapilib.base import Base, MayBeReferenced

_log = logging.getLogger(__name__)


def serialize_spec(spec: OpenAPI, disable_referencing=False) -> Dict:
    """
    Serialize an OpenAPI spec.
    """
    if spec.components is not None and spec.components is not SKIP:
        components = spec.components
    else:
        components = Components()

    serialized = SerializationContext(
        components=components
    ).serialize(spec)

    # Serialize components with referencing disabled, in order for them
    # not to try circular-reference themselves .
    components = SerializationContext(
        disable_referencing=True,
    ).serialize(components)

    serialized['components'] = components

    return serialized


def serialize(spec: Base) -> Dict:
    """
    Recursively convert a spec to a dictionary.

    This method can be used for testing and development, or as a utility.

    If you want to serialize an :any:`OpenAPI` object,
    use :any:`serialize_spec`.

    References are not generated by this method.
    """
    # Serialize components with referencing disabled, in order for them
    # not to try circular-reference themselves .
    return SerializationContext(
        disable_referencing=True,
    ).serialize(spec)


@attr.s(slots=True)
class SerializationContext:
    disable_referencing: bool = attr.ib(default=False)
    components: Optional['Components'] = attr.ib(default=None)

    def serialize(self, obj: Union['Base', Any]):
        if isinstance(obj, Base):
            # Try to serialize as a reference
            reference = self.serialize_maybe_reference(obj)
            if reference is not None:
                value = reference
            else:
                value = spec_to_dict(obj)
        else:
            value = obj

        # Handled possibly nested values

        return self.serialize_value(value)

    def serialize_maybe_reference(self, spec: 'Base'):
        """
        Serialize an object that may be referenced by storing the definition
        in Components and returning a reference.
        """
        if not isinstance(spec, MayBeReferenced):
            _log.debug(
                'Object of type %s may not be referenced',
                type(spec)
            )
            return

        if self.disable_referencing:
            _log.debug(
                'Referencing disabled, not referencing. ref_name=%r',
                spec.ref_name,
            )
            return

        if spec.ref_name is None:
            _log.debug('No ref_name set, not referencing. spec=%')
            return

        # Store definition in context, return reference
        _log.debug(
            'trying to reference, ref_name=%r',
            spec.ref_name,
        )
        existing = self.components.get_stored(spec)
        if existing:
            _log.debug(
                'Found existing: %r.',
                existing.ref_name,
                extra=dict(
                    diff=LazyPretty(
                        lambda: deepdiff.DeepDiff(
                            serialize(existing),
                            serialize(spec)
                        )
                    ),
                )
            )
        else:
            _log.debug(
                'Storing %r:%s',
                spec.ref_name,
                LazyPretty(lambda: serialize(spec)),
            )
            self.components.store(spec)

        return spec_to_dict(
            self.components.get_ref(
                spec,
            )
        )

    def serialize_value(self, value):
        """
        Serializes container types, such as list, dict, tuple, set.
        """
        if isinstance(value, dict):
            return {
                self.serialize(k): self.serialize(v)
                for k, v in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [self.serialize(v) for v in value]

        return value


def spec_to_dict(spec: 'Base'):
    """
    Serializes instances of objects that inherit from
    :class:`Base`.
    """

    fields = spec.fields_by_name()

    filtered = attr.asdict(
        spec,
        filter=filter_attributes,
        recurse=False,
    )

    serialized = {
        rename_key(key, fields[key]): value
        for key, value in filtered.items()
    }

    return serialized


def rename_key(key: str, a: attr.Attribute) -> str:
    if key.startswith('_'):
        assert len(key) > 1
        key = key[1:]

    if key.endswith('_'):
        assert len(key) > 1
        key = key[:-1]

    #: Name of field according to spec.
    spec_name = a.metadata.get('spec_name', stringcase.camelcase(key))
    return spec_name


def filter_attributes(attribute: attr.Attribute, value):
    is_skipped = value is SKIP
    non_spec = attribute.metadata.get('non_spec')

    return (not is_skipped) and not non_spec