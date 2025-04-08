with open("D:/desktop_temp/Aayush_Gadiya.jpg", "rb") as file:
    binary_data = file.read()
    hex_data = binary_data.hex()
    print(hex_data)
