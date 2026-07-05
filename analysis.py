import pandas as pd
import numpy as np 

from dataframe import read_file, year_bound, graph


print('Willkommen zur Wetterdatenanalyse!')
print(f'1 - Ausgabe einer Tabelle \n2 - Ausgabe eines Graphens')

i = 1 
while i == 1:
    var1 = input('Eingabe: ')
    if var1 == '1' or var1 == '2':
        break

jahr1 = 0 
jahr2 = 0

while jahr1 >= jahr2 or not (1934 <= jahr1 <= 2026) or not (1934 <= jahr2 <= 2026):    
    jahr1 = int(input('Jahr Beginn: '))
    jahr2 = int(input('Jahr Ende: '))

df = read_file('Wetterdaten_DD_1934_2026.csv')
temp_data, rain_data = year_bound(df, 2000, 2003)


if var1 == '1':
    print(df)
elif var1 == '2':
    graph(temp_data)
    graph(rain_data)
    


