from collections import namedtuple

User = namedtuple('User', ['username', 'password', 'permissions'])

user_map = {
    user.username: user for user in [
        User('vadim', 'qwerty', ('realtime_video', 'download')),
    ]
}
