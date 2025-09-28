from flask_wtf import FlaskForm
from wtforms import (StringField, TextAreaField, BooleanField, 
                     IntegerField, SubmitField, FloatField, 
                     SelectField, DateField, HiddenField
)
from wtforms.validators import DataRequired, NumberRange

class StrategyForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    description = TextAreaField("Description")
    video_url = StringField("YouTube Video URL")
    signals = StringField("Signals")
    difficulty = StringField("Difficulty Level")
    timeframe = StringField("Timeframe")
    gain = StringField("Gain %")
    users = IntegerField("Users")
    is_active = BooleanField("Active?")
    submit = SubmitField("Save")

class StrategyPopupForm(FlaskForm):
    strategy_name = StringField("Strategy", validators=[DataRequired()])
    symbol_tv = StringField("Strategy Symbol", validators=[DataRequired()])  # <-- change
    amount = FloatField("Enter Amount (INR)", validators=[DataRequired(), NumberRange(min=0)])
    leverage = IntegerField("Leverage", validators=[NumberRange(min=0, max=125)])
    # timeframe = SelectField("Timeframe", choices=[("1m","1m"),("5m","5m"),("15m","15m"),("1h","1h")], default="15m")
    timeframe = SelectField(
        label="Timeframe",
        choices=[
            ("1m", "1 minute"),
            ("5m", "5 minutes"),
            ("15m", "15 minutes"),
            ("1h", "1 hour"),
            ("2h", "2 hours"),
            ("4h", "4 hours"),
            ("8h", "8 hours"),
            ("1d", "1 day"),
            ("1w", "1 week")
        ],
        default="15m"
    )
    start_date = DateField("From Date", validators=[DataRequired()])
    end_date = DateField("To Date", validators=[DataRequired()])
    config_id = HiddenField()
    submit = SubmitField("Create Strategy")
