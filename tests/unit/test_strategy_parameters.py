import unittest

from strategylab.strategies import ParameterDefinition, ParameterSchema, ParameterType


class StrategyParametersTest(unittest.TestCase):
    def test_schema_applies_defaults(self) -> None:
        schema = ParameterSchema(
            definitions=(
                ParameterDefinition("lookback", ParameterType.INTEGER, default=20, min_value=1),
            )
        )

        values = schema.validate({})

        self.assertEqual(values["lookback"], 20)

    def test_schema_accepts_valid_override(self) -> None:
        schema = ParameterSchema(
            definitions=(
                ParameterDefinition("threshold", ParameterType.FLOAT, default=100.0, min_value=0.0),
            )
        )

        values = schema.validate({"threshold": 123.5})

        self.assertEqual(values["threshold"], 123.5)

    def test_schema_rejects_wrong_type(self) -> None:
        schema = ParameterSchema(
            definitions=(
                ParameterDefinition("enabled", ParameterType.BOOLEAN, default=True),
            )
        )

        with self.assertRaises(ValueError):
            schema.validate({"enabled": "yes"})

    def test_schema_rejects_min_max_violations(self) -> None:
        schema = ParameterSchema(
            definitions=(
                ParameterDefinition("strength", ParameterType.FLOAT, default=0.5, min_value=0.0, max_value=1.0),
            )
        )

        with self.assertRaises(ValueError):
            schema.validate({"strength": 1.5})

    def test_schema_rejects_unknown_parameters(self) -> None:
        schema = ParameterSchema(definitions=())

        with self.assertRaises(ValueError):
            schema.validate({"unknown": 1})

    def test_parameter_definition_round_trip(self) -> None:
        definition = ParameterDefinition(
            "mode",
            ParameterType.STRING,
            default="neutral",
            description="mode selector",
        )

        restored = ParameterDefinition.from_dict(definition.to_dict())

        self.assertEqual(restored, definition)


if __name__ == "__main__":
    unittest.main()

