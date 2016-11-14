package ru.ispras.lingvodoc.frontend.app.model

import upickle.Js

import scala.scalajs.js.Date
import scala.scalajs.js.annotation.JSExportAll


@JSExportAll
case class User(id: Int,
                var login: String,
                var email: Option[String],
                var name: String,
                var intlName: String,
                var birthday: Date,
                var isActive: Boolean,
                var created: Date) {

  var defaultLocale: Option[Int] = None
  var organizations: Seq[Unit] = Seq()
}

object User {
  implicit val writer = upickle.default.Writer[User] {
    user =>
      var values = Seq[(String, Js.Value)](
        ("id", Js.Num(user.id)),
        ("login", Js.Str(user.login)),
        ("name", Js.Str(user.name)),
        ("intl_name", Js.Str(user.intlName)),
        ("birthday", Js.Str(s"${user.birthday.getFullYear()}-${user.birthday.getMonth()}-${user.birthday.getDay()}")),
        ("is_active", if (user.isActive) Js.True else Js.False),
        ("created_at", Js.Num(user.created.getTime().toInt))
      )

      user.email foreach{ e =>
        values = values :+ ("email", Js.Str(e))
      }

      Js.Obj(values: _*)
  }

  implicit val reader = upickle.default.Reader[User] {
    case js: Js.Obj =>
      val id = js("id").asInstanceOf[Js.Num].value.toInt
      val login = js("login").asInstanceOf[Js.Str].value
      val name = js("name").asInstanceOf[Js.Str].value
      val intlName = js("intl_name").asInstanceOf[Js.Str].value

      val isActive: Boolean = js("is_active") match {
        case Js.True => true
        case Js.False => false
        case _ => false
      }

      val email = js.value.find(_._1 == "email").map(_._2.str)

      val birthday = new Date(js("birthday").str)
      val created = new Date(js("created_at").num * 1000)

      User(id, login, email, name, intlName, birthday, isActive, created)
  }
}