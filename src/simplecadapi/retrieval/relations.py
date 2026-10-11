"""High-confidence semantic input roles for related API expansion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .producer_index import validate_catalog_api_ids


@dataclass(frozen=True)
class ProducerOption:
    """One producer workflow, listed in dependency order."""

    api_ids: tuple[str, ...]
    weight: float


@dataclass(frozen=True)
class InputRole:
    """Meaningful geometry input position on one consumer API."""

    name: str
    geometry_types: tuple[str, ...]
    options: tuple[ProducerOption, ...] = ()
    max_producers: int = 1
    allow_type_producers: bool = False
    requires_closed_profile: bool = False
    closed_type_producer_ids: tuple[str, ...] = ()
    type_producer_weight: float = 1.0


@dataclass(frozen=True)
class ConsumerRelation:
    """All semantic input roles that can supply one consumer API."""

    consumer_id: str
    roles: tuple[InputRole, ...]


RELATED_API_RELATIONS = (
    ConsumerRelation(
        consumer_id="sweep_rsolid",
        roles=(
            InputRole(
                name="path",
                geometry_types=("Wire",),
                options=(
                    ProducerOption(("make_spline_rwire",), 1.00),
                    ProducerOption(
                        ("make_three_point_arc_redge", "make_wire_from_edges_rwire"),
                        0.80,
                    ),
                    ProducerOption(
                        ("make_angle_arc_redge", "make_wire_from_edges_rwire"),
                        0.75,
                    ),
                    ProducerOption(("make_polyline_rwire",), 0.45),
                ),
            ),
            InputRole(
                name="profile",
                geometry_types=("Face",),
                options=(
                    ProducerOption(("make_rectangle_rface",), 1.00),
                    ProducerOption(("make_circle_rface",), 0.90),
                    ProducerOption(("make_face_from_wire_rface",), 0.65),
                ),
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="loft_rsolid",
        roles=(
            InputRole(
                name="profiles",
                geometry_types=("Wire",),
                max_producers=2,
                allow_type_producers=True,
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="extrude_rsolid",
        roles=(
            InputRole(
                name="profile",
                geometry_types=("Wire", "Face"),
                allow_type_producers=True,
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="revolve_rsolid",
        roles=(
            InputRole(
                name="profile",
                geometry_types=("Wire", "Face"),
                allow_type_producers=True,
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="helical_sweep_rsolid",
        roles=(
            InputRole(
                name="profile",
                geometry_types=("Wire",),
                allow_type_producers=True,
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="make_wire_from_edges_rwire",
        roles=(
            InputRole(
                name="edges",
                geometry_types=("Edge",),
                options=(ProducerOption(("make_spline_redge",), 1.00),),
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="make_face_from_wire_rface",
        roles=(
            InputRole(
                name="wire",
                geometry_types=("Wire",),
                allow_type_producers=True,
                requires_closed_profile=True,
                closed_type_producer_ids=(
                    "make_circle_rwire",
                    "make_rectangle_rwire",
                ),
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="make_face_from_wires_rface",
        roles=(
            InputRole(
                name="outer_wire",
                geometry_types=("Wire",),
                allow_type_producers=True,
                requires_closed_profile=True,
                closed_type_producer_ids=(
                    "make_circle_rwire",
                    "make_rectangle_rwire",
                ),
            ),
            InputRole(
                name="inner_wires",
                geometry_types=("Wire",),
                allow_type_producers=True,
                requires_closed_profile=True,
                closed_type_producer_ids=(
                    "make_circle_rwire",
                    "make_rectangle_rwire",
                ),
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="fillet_rsolid",
        roles=(
            InputRole(
                name="edges",
                geometry_types=("Edge", "ShapeSelector"),
                options=(ProducerOption(("select_edges_by_tag",), 1.00),),
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="chamfer_rsolid",
        roles=(
            InputRole(
                name="edges",
                geometry_types=("Edge", "ShapeSelector"),
                options=(ProducerOption(("select_edges_by_tag",), 1.00),),
            ),
        ),
    ),
    ConsumerRelation(
        consumer_id="shell_rsolid",
        roles=(
            InputRole(
                name="faces_to_remove",
                geometry_types=("Face", "ShapeSelector"),
                options=(ProducerOption(("select_faces_by_tag",), 1.00),),
            ),
        ),
    ),
)

RELATIONS_BY_CONSUMER = {
    relation.consumer_id: relation for relation in RELATED_API_RELATIONS
}


def configured_related_api_ids() -> tuple[str, ...]:
    """Return every consumer and producer id named by the relation table."""
    api_ids: list[str] = []
    for relation in RELATED_API_RELATIONS:
        api_ids.append(relation.consumer_id)
        for role in relation.roles:
            api_ids.extend(role.closed_type_producer_ids)
            for option in role.options:
                api_ids.extend(option.api_ids)
    return tuple(api_ids)


def validate_related_api_relations(catalog: Sequence[Mapping]) -> None:
    """Fail startup when the checked-in relation table references a missing API."""
    validate_catalog_api_ids(catalog, configured_related_api_ids())


__all__ = [
    "ConsumerRelation",
    "InputRole",
    "ProducerOption",
    "RELATED_API_RELATIONS",
    "RELATIONS_BY_CONSUMER",
    "configured_related_api_ids",
    "validate_related_api_relations",
]
