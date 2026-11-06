"use strict";

class ActorError extends Error {
  constructor(code, message, hint = "") {
    super(message);
    this.name = "ActorError";
    this.code = code;
    this.hint = hint;
  }
}

function asActorError(error) {
  if (error instanceof ActorError) return error;
  return new ActorError("unexpected", error && error.message ? error.message : String(error));
}

module.exports = { ActorError, asActorError };
